import io
import os
import runpy
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from werkzeug.exceptions import HTTPException

import app as fraud_app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = fraud_app.app.test_client()

    def test_print_stacktrace_to_stdout_writes_context(self):
        fake_stdout = io.StringIO()

        with patch.object(fraud_app.sys, "stdout", fake_stdout), patch.object(fraud_app.traceback, "print_exc") as print_exc_mock:
            fraud_app.print_stacktrace_to_stdout("unit_test")

        self.assertIn("[unit_test]", fake_stdout.getvalue())
        print_exc_mock.assert_called_once_with(file=fake_stdout)

    def test_generate_once_posts_messages_to_model_service(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"result": "tool output"}

        with patch.object(fraud_app.http_requests, "post", return_value=response) as post_mock:
            result = fraud_app.generate_once([{"role": "user", "content": "hello"}])

        post_mock.assert_called_once_with(
            f"{fraud_app.MODEL_SERVICE_URL}/generate",
            json={"messages": [{"role": "user", "content": "hello"}]},
            timeout=None,
        )
        self.assertEqual(result, "tool output")

    def test_generate_once_raises_runtime_error_from_json_error_response(self):
        response = Mock()
        response.status_code = 503
        response.headers = {"content-type": "application/json"}
        response.json.return_value = {"error": "service down"}

        with patch.object(fraud_app.http_requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "service down"):
                fraud_app.generate_once([{"role": "user", "content": "hello"}])

    def test_generate_once_raises_runtime_error_for_non_json_error_response(self):
        response = Mock()
        response.status_code = 500
        response.headers = {"content-type": "text/plain"}

        with patch.object(fraud_app.http_requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Model service returned 500"):
                fraud_app.generate_once([{"role": "user", "content": "hello"}])

    def test_parse_tool_call_accepts_supported_formats(self):
        cases = [
            (
                "```json\n{\"tool\":\"investigation_fraud\",\"args\":{\"query\":\"SELECT 1\"}}\n```",
                "SELECT 1",
            ),
            (
                "Use this {\"tool\":\"investigation_fraud\",\"args\":{\"query\":\"SELECT 2\"}} now",
                "SELECT 2",
            ),
            (
                "{'tool': 'investigation_fraud', 'args': {'query': 'SELECT 3'}}",
                "SELECT 3",
            ),
            (
                '{"tool": "investigation_fraud", "args": "{\\"query\\": \\\"SELECT 5\\\"}"}',
                "SELECT 5",
            ),
            (
                '{"tool":"investigation_fraud","args":{"query":"SELECT *\nFROM investigations"}}',
                "SELECT * FROM investigations",
            ),
            (
                "SELECT * FROM investigations",
                "SELECT * FROM investigations",
            ),
        ]

        for text, expected_query in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    fraud_app.parse_tool_call(text),
                    {"tool": "investigation_fraud", "args": {"query": expected_query}},
                )

    def test_parse_tool_call_rejects_invalid_payloads(self):
        cases = [
            '{"tool":"different_tool","args":{"query":"SELECT 1"}}',
            '{"tool":"investigation_fraud","args":{}}',
            '{"tool":"investigation_fraud","args":{"query":"   "}}',
            '{"tool":"investigation_fraud","args":"not a dict"}',
            "not valid output",
        ]

        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(fraud_app.parse_tool_call(text))

    def test_investigation_fraud_requires_token(self):
        with fraud_app.app.test_request_context("/api/fraud"):
            with self.assertRaises(HTTPException) as error:
                fraud_app.investigation_fraud("SELECT 1")

        self.assertEqual(error.exception.code, 401)

    def test_investigation_fraud_returns_rows_from_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "fraud.sqlite")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE investigations (transaction_id TEXT, fraud_detected TEXT)")
            conn.execute("INSERT INTO investigations VALUES ('tx-1', 'true')")
            conn.commit()
            conn.close()

            with patch.dict(os.environ, {"DB_CONNECTION_STRING": db_path}, clear=False):
                with fraud_app.app.test_request_context(
                    "/api/fraud",
                    headers={"token": fraud_app.allowed_tokens[0]},
                ):
                    rows = fraud_app.investigation_fraud("SELECT * FROM investigations")

        self.assertEqual(rows, [{"transaction_id": "tx-1", "fraud_detected": "true"}])

    def test_investigate_transaction_orchestrates_tool_and_final_answer(self):
        tool_call = (
            '{"tool":"investigation_fraud","args":{"query":"SELECT * FROM investigations WHERE fraud_detected=\'true\'"}}'
        )
        investigation_rows = [{"transaction_id": "tx-123", "fraud_detected": "true"}]

        with patch.object(fraud_app, "generate_once", side_effect=[tool_call, "likely fraudulent"]) as generate_mock, patch.object(
            fraud_app,
            "investigation_fraud",
            return_value=investigation_rows,
        ) as investigation_mock:
            response = self.client.post(
                "/api/fraud",
                json={"question": "Is this fraudulent?"},
                headers={"token": fraud_app.allowed_tokens[0]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"response": [{"apertus": "likely fraudulent"}]})
        self.assertEqual(generate_mock.call_count, 2)
        investigation_mock.assert_called_once_with(
            "SELECT * FROM investigations WHERE fraud_detected='true'"
        )

        first_messages = generate_mock.call_args_list[0].args[0]
        second_messages = generate_mock.call_args_list[1].args[0]
        self.assertIs(first_messages, second_messages)
        self.assertEqual(first_messages[0]["role"], "system")
        self.assertEqual(first_messages[1], {"role": "user", "content": "Is this fraudulent?"})
        self.assertEqual(len(second_messages), 3)
        self.assertIn("Tool execution result:", second_messages[2]["content"])
        self.assertIn("tx-123", second_messages[2]["content"])

    def test_investigate_transaction_requires_question(self):
        response = self.client.get("/api/fraud")

        self.assertEqual(response.status_code, 400)

    def test_investigate_transaction_supports_get_requests(self):
        with patch.object(fraud_app, "generate_once", side_effect=["SELECT * FROM investigations", "answer"]) as generate_mock, patch.object(
            fraud_app,
            "investigation_fraud",
            return_value=[],
        ):
            response = self.client.get(
                "/api/fraud?question=Check%20it",
                headers={"token": fraud_app.allowed_tokens[0]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"response": [{"apertus": "answer"}]})
        self.assertEqual(generate_mock.call_args_list[0].args[0][1]["content"], "Check it")

    def test_investigate_transaction_handles_tool_call_generation_failure(self):
        with patch.object(fraud_app, "generate_once", side_effect=RuntimeError("model offline")):
            response = self.client.post("/api/fraud", json={"question": "hello"})

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()["response"][0]
        self.assertEqual(payload["apertus"], "I could not generate an investigation tool call.")
        self.assertEqual(payload["error"], "model offline")

    def test_investigate_transaction_handles_invalid_tool_call(self):
        with patch.object(fraud_app, "generate_once", return_value="nonsense"):
            response = self.client.post("/api/fraud", json={"question": "hello"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["response"][0]
        self.assertEqual(payload["error"], "Tool output format did not match expected schema.")
        self.assertEqual(payload["raw_output"], "nonsense")

    def test_investigate_transaction_handles_tool_execution_failure(self):
        tool_call = '{"tool":"investigation_fraud","args":{"query":"SELECT 1"}}'

        with patch.object(fraud_app, "generate_once", return_value=tool_call), patch.object(
            fraud_app,
            "investigation_fraud",
            side_effect=RuntimeError("db broken"),
        ):
            response = self.client.post("/api/fraud", json={"question": "hello"})

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()["response"][0]
        self.assertEqual(payload["apertus"], "Investigation tool execution failed.")
        self.assertEqual(payload["error"], "db broken")
        self.assertEqual(payload["sql_query"], "SELECT 1")

    def test_investigate_transaction_handles_final_answer_generation_failure(self):
        tool_call = '{"tool":"investigation_fraud","args":{"query":"SELECT 1"}}'

        with patch.object(fraud_app, "generate_once", side_effect=[tool_call, RuntimeError("answer failed")]), patch.object(
            fraud_app,
            "investigation_fraud",
            return_value=[],
        ):
            response = self.client.post(
                "/api/fraud",
                json={"question": "hello"},
                headers={"token": fraud_app.allowed_tokens[0]},
            )

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()["response"][0]
        self.assertEqual(payload["apertus"], "Final answer generation failed.")
        self.assertEqual(payload["error"], "answer failed")

    def test_setup_db_creates_sample_rows_and_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "db.sqlite")
            with open(db_path, "w", encoding="utf-8") as handle:
                handle.write("stale")

            with patch.dict(os.environ, {"DB_CONNECTION_STRING": db_path}, clear=False):
                fraud_app.setupDB()
                fraud_app.setupDB()

            conn = sqlite3.connect(db_path)
            try:
                row_count = conn.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(row_count, 2)

    def test_main_entrypoint_initializes_db_and_starts_server(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "main.sqlite")
            with patch.dict(os.environ, {"DB_CONNECTION_STRING": db_path}, clear=False), patch("flask.app.Flask.run") as run_mock:
                runpy.run_module("app", run_name="__main__")

            conn = sqlite3.connect(db_path)
            try:
                row_count = conn.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(row_count, 2)
        run_mock.assert_called_once_with(host="0.0.0.0", port=9000)


if __name__ == "__main__":
    unittest.main()