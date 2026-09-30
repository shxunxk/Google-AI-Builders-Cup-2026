"""Shared policy corpus index for Immune City agents.

One ChromaDB index over Agents/corpus, shared by every agent
(defender, attacker, courtroom). Agents query the same collection
with different queries — indexing is done once, centrally.

Run:  python -m Agents.build_index
"""
import shutil
import chromadb
from chromadb.utils import embedding_functions
import pdfplumber
from pathlib import Path
import argparse

AGENTS_DIR = Path(__file__).parent
CORPUS_DIR = AGENTS_DIR / "corpus"
CHROMA_PATH = AGENTS_DIR / "chroma_db"
COLLECTION = "policy_corpus"
EMBED_MODEL = "all-MiniLM-L6-v2"
MIN_CHUNK_CHARS = 100


def get_ef():
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBED_MODEL
    )


def build_index(verbose: bool = True, rebuild: bool = False) -> str:
    """Ingest every PDF under Agents/corpus. Idempotent — safe to re-run.

    rebuild=True wipes the index first (use when metadata schema changes).
    """
    if not CORPUS_DIR.exists():
        raise FileNotFoundError(f"No corpus dir at {CORPUS_DIR}")

    pdfs = sorted(CORPUS_DIR.rglob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs found under {CORPUS_DIR}")

    if rebuild and CHROMA_PATH.exists():
        if verbose:
            print(f"rebuild: wiping {CHROMA_PATH}")
        shutil.rmtree(CHROMA_PATH)

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection(
        COLLECTION, embedding_function=get_ef()
    )
    existing = set(collection.get(include=[])["ids"])

    added = 0
    failures = []
    empty = []                      # PDFs that yielded no usable text
    per_pdf = []
    for pdf_path in pdfs:
        chunks = 0
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_no, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    chunk_id = f"{pdf_path.stem}_p{page_no}"
                    if not text or len(text) < MIN_CHUNK_CHARS:
                        continue
                    chunks += 1
                    if chunk_id in existing:
                        continue
                    collection.add(
                        documents=[text],
                        metadatas=[{
                            "source": pdf_path.name,
                            "page": page_no,
                            "category": pdf_path.relative_to(CORPUS_DIR).parts[0]
                                       if len(pdf_path.relative_to(CORPUS_DIR).parts) > 1
                                       else "general",
                            "path": str(pdf_path.relative_to(CORPUS_DIR)),
                        }],
                        ids=[chunk_id],
                    )
                    added += 1
            if chunks == 0:
                empty.append(pdf_path)
            per_pdf.append((pdf_path, chunks))
        except Exception as e:                 # one bad PDF shouldn't kill the run
            failures.append(f"{pdf_path.name}: {type(e).__name__}")

    if verbose:
        indexed = len(per_pdf) - len(empty)
        print(f"{len(pdfs)} PDFs -> {collection.count()} chunks "
              f"({added} new, {len(existing)} existing)")
        print(f"indexed: {indexed}/{len(pdfs)} PDFs")
        print(f"index:  {CHROMA_PATH}")
        for f in failures:
            print(f"  ! error:  {f}")
        for p in empty:
            print(f"  ! no text: {p.relative_to(CORPUS_DIR)}")
        if empty:
            print(f"\n  {len(empty)} PDF(s) have no text layer (image-only scans).")
            print("  pdfplumber/PyMuPDF cannot read them. Either re-download a")
            print("  text-layer copy, or run OCR first (ocrmypdf/tesseract), or")
            print("  convert them to .md summaries and put those in corpus/.")

    return str(CHROMA_PATH)


def get_collection():
    """Open the shared index. Run build_index() first if this raises."""
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_collection(COLLECTION, embedding_function=get_ef())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the shared policy corpus index")
    ap.add_argument("--rebuild", action="store_true",
                    help="wipe the existing index and re-ingest everything")
    build_index(rebuild=ap.parse_args().rebuild)