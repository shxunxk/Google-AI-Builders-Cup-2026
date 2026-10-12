import unittest
from unittest.mock import patch

import pandas as pd

from Agents.fincity import data_loader


def sample_transactions(include_labels=False):
    rows = [
        (1, "TRANSFER", 1000.0, "C1", 1000.0, 0.0, "C2", 0.0, 1000.0),
        (1, "TRANSFER", 1000.0, "C2", 1000.0, 0.0, "C3", 0.0, 1000.0),
        (1, "TRANSFER", 1000.0, "C3", 1000.0, 0.0, "C1", 0.0, 1000.0),
        (2, "PAYMENT", 10.0, "C4", 20.0, 10.0, "M1", 0.0, 10.0),
        (3, "CASH_OUT", 500.0, "C5", 500.0, 0.0, "C6", 0.0, 500.0),
    ]
    columns = [
        "step", "type", "amount", "nameOrig", "oldbalanceOrg",
        "newbalanceOrig", "nameDest", "oldbalanceDest", "newbalanceDest",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    if include_labels:
        frame["isFraud"] = [1, 1, 1, 0, 0]
    return frame


class FinCityDataLoaderTests(unittest.TestCase):
    def test_time_window_filters_edges_and_builds_review_cluster(self):
        transactions = sample_transactions()
        with patch.object(data_loader, "load_transactions", return_value=transactions):
            nodes, edges = data_loader.build_graph(max_nodes=20, time_window=(1, 1))
            rings = data_loader.get_fraud_rings(nodes, edges)

        self.assertEqual(set(nodes), {"C1", "C2", "C3"})
        self.assertEqual(len(edges), 3)
        self.assertEqual(len(rings), 1)
        self.assertEqual(rings[0]["risk_basis"], "review_heuristic")
        self.assertGreater(rings[0]["signal_rate"], 0)
        self.assertEqual(rings[0]["fraud_rate"], 0)
        self.assertTrue(all(edge["fraud_count"] == 0 for edge in edges))
        self.assertEqual(set(rings[0]["nodes"]), {"C1", "C2", "C3"})

    def test_labelled_transactions_are_reported_as_observed(self):
        transactions = sample_transactions(include_labels=True)
        with patch.object(data_loader, "load_transactions", return_value=transactions):
            nodes, edges = data_loader.build_graph(max_nodes=20, time_window=(1, 1))
            rings = data_loader.get_fraud_rings(nodes, edges)

        self.assertEqual(nodes["C1"]["risk_basis"], "observed_label")
        self.assertEqual(nodes["C1"]["risk_score"], 1.0)
        self.assertEqual(rings[0]["risk_basis"], "observed_label")
        self.assertEqual(rings[0]["fraud_rate"], 1.0)

    def test_minimum_transaction_filter_and_empty_window(self):
        transactions = sample_transactions()
        with patch.object(data_loader, "load_transactions", return_value=transactions):
            filtered = data_loader.build_graph(min_txn_count=2, max_nodes=20)
            empty = data_loader.build_graph(max_nodes=20, time_window=(10, 12))

        self.assertEqual(filtered, ({}, []))
        self.assertEqual(empty, ({}, []))

    def test_time_windows_cover_each_available_step_once(self):
        transactions = sample_transactions()
        windows = data_loader.get_time_windows(transactions, n_windows=20)
        self.assertEqual(windows, [(1, 1), (2, 2), (3, 3)])


if __name__ == "__main__":
    unittest.main()
