import importlib
import io
import runpy
import sys
import types
import types
import unittest
from unittest.mock import Mock, patch


class FakeTensor:
    def __init__(self, values):
        self.values = list(values)
        self.shape = (1, len(self.values))

    def to(self, _device):
        return self

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self.values[index]
        return self.values[index]


class FakeBatch:
    def __init__(self, input_ids, attention_mask):
        self.input_ids = input_ids
        self.attention_mask = attention_mask


def load_model_service_with_mocks(
    *,
    pad_token_id=None,
    chat_template_result_kind="batch",
    include_attention_mask=True,
    model_load_error=None,
):
    tokenizer = Mock()
    tokenizer.pad_token_id = pad_token_id
    tokenizer.eos_token = "<eos>"
    tokenizer.eos_token_id = 99
    tokenizer.pad_token = None

    if chat_template_result_kind == "batch":
        tokenizer.apply_chat_template.return_value = FakeBatch(
            FakeTensor([10, 20, 30]),
            FakeTensor([1, 1, 1]),
        )
    elif chat_template_result_kind == "dict":
        tokenizer.apply_chat_template.return_value = {
            "input_ids": FakeTensor([10, 20, 30]),
            **({"attention_mask": FakeTensor([1, 1, 1])} if include_attention_mask else {}),
        }
    else:
        tokenizer.apply_chat_template.return_value = FakeTensor([10, 20, 30])

    tokenizer.decode.return_value = "decoded response"

    base_model = Mock(name="base_model")
    adapted_model = Mock(name="adapted_model")
    adapted_model.generate.return_value = [FakeTensor([10, 20, 30, 40, 50])]

    tokenizer_from_pretrained = Mock(return_value=tokenizer)
    model_from_pretrained = Mock(return_value=base_model)
    peft_from_pretrained = Mock(return_value=adapted_model)

    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.float32 = "float32"
    fake_torch.ones_like = lambda tensor: FakeTensor([1] * len(tensor.values))
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)

    fake_transformers = types.ModuleType("transformers")

    class FakeBitsAndBytesConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_transformers.AutoTokenizer = types.SimpleNamespace(
        from_pretrained=tokenizer_from_pretrained
    )

    def fake_model_loader(*args, **kwargs):
        if model_load_error is not None:
            raise model_load_error
        return model_from_pretrained(*args, **kwargs)

    fake_transformers.AutoModelForCausalLM = types.SimpleNamespace(
        from_pretrained=fake_model_loader
    )
    fake_transformers.BitsAndBytesConfig = FakeBitsAndBytesConfig

    fake_peft = types.ModuleType("peft")
    fake_peft.PeftModel = types.SimpleNamespace(from_pretrained=peft_from_pretrained)

    original_modules = {
        name: sys.modules.get(name)
        for name in ("torch", "transformers", "peft", "model_service")
    }

    sys.modules["torch"] = fake_torch
    sys.modules["transformers"] = fake_transformers
    sys.modules["peft"] = fake_peft
    sys.modules.pop("model_service", None)

    try:
        module = importlib.import_module("model_service")
    finally:
        sys.modules.pop("model_service", None)
        for name, original in original_modules.items():
            if name == "model_service":
                continue
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    return {
        "module": module,
        "tokenizer": tokenizer,
        "tokenizer_from_pretrained": tokenizer_from_pretrained,
        "model_from_pretrained": model_from_pretrained,
        "peft_from_pretrained": peft_from_pretrained,
        "base_model": base_model,
        "adapted_model": adapted_model,
    }


class ModelServiceTests(unittest.TestCase):
    def test_print_stacktrace_to_stdout_writes_context(self):
        loaded = load_model_service_with_mocks()
        module = loaded["module"]
        fake_stdout = io.StringIO()

        with patch.object(module.sys, "stdout", fake_stdout), patch.object(module.traceback, "print_exc") as print_exc_mock:
            module.print_stacktrace_to_stdout("unit_test")

        self.assertIn("[unit_test]", fake_stdout.getvalue())
        print_exc_mock.assert_called_once_with(file=fake_stdout)

    def test_import_loads_tokenizer_base_model_and_adapter(self):
        loaded = load_model_service_with_mocks()
        module = loaded["module"]

        loaded["tokenizer_from_pretrained"].assert_called_once_with("./Apertus-8B-Instruct-2509")
        loaded["model_from_pretrained"].assert_called_once()
        loaded["peft_from_pretrained"].assert_called_once_with(
            loaded["base_model"],
            "./pwnednext",
        )
        self.assertIs(module.model, loaded["adapted_model"])
        self.assertEqual(module.tokenizer.pad_token, module.tokenizer.eos_token)

    def test_import_failure_switches_to_fallback_mode(self):
        loaded = load_model_service_with_mocks(model_load_error=RuntimeError("no gpu"))
        module = loaded["module"]

        self.assertIsNone(module.model)
        self.assertEqual(module.model_load_error, "no gpu")

    def test_generate_once_delegates_to_model_generate_and_decodes_new_tokens(self):
        loaded = load_model_service_with_mocks()
        module = loaded["module"]
        messages = [{"role": "user", "content": "check transaction"}]

        result = module.generate_once(messages)

        loaded["tokenizer"].apply_chat_template.assert_called_once_with(
            messages,
            add_generation_prompt=True,
            return_tensors="pt",
        )
        loaded["adapted_model"].generate.assert_called_once_with(
            loaded["tokenizer"].apply_chat_template.return_value.input_ids,
            attention_mask=loaded["tokenizer"].apply_chat_template.return_value.attention_mask,
            max_new_tokens=384,
            temperature=0.2,
            do_sample=True,
            eos_token_id=loaded["tokenizer"].eos_token_id,
            pad_token_id=loaded["tokenizer"].pad_token_id,
        )
        loaded["tokenizer"].decode.assert_called_once_with([40, 50], skip_special_tokens=True)
        self.assertEqual(result, "decoded response")

    def test_generate_once_handles_dict_chat_template_without_attention_mask(self):
        loaded = load_model_service_with_mocks(
            chat_template_result_kind="dict",
            include_attention_mask=False,
        )
        module = loaded["module"]

        result = module.generate_once([{"role": "user", "content": "dict mode"}])

        loaded["adapted_model"].generate.assert_called_once()
        self.assertEqual(
            loaded["adapted_model"].generate.call_args.kwargs["attention_mask"].values,
            [1, 1, 1],
        )
        self.assertEqual(result, "decoded response")

    def test_generate_once_handles_tensor_chat_template_output(self):
        loaded = load_model_service_with_mocks(chat_template_result_kind="tensor")
        module = loaded["module"]

        result = module.generate_once([{"role": "user", "content": "tensor mode"}])

        loaded["adapted_model"].generate.assert_called_once()
        self.assertEqual(
            loaded["adapted_model"].generate.call_args.args[0].values,
            [10, 20, 30],
        )
        self.assertEqual(result, "decoded response")

    def test_generate_once_returns_fallback_sql_when_model_is_unavailable(self):
        loaded = load_model_service_with_mocks(model_load_error=RuntimeError("unavailable"))
        module = loaded["module"]

        result = module.generate_once([
            {"role": "system", "content": module.SYSTEM_PROMPT_SQL},
            {"role": "user", "content": "Investigate this"},
        ])

        self.assertIn('"tool": "investigation_fraud"', result)

    def test_generate_once_returns_fallback_text_when_model_is_unavailable(self):
        loaded = load_model_service_with_mocks(model_load_error=RuntimeError("unavailable"))
        module = loaded["module"]

        result = module.generate_once([{"role": "user", "content": "hello"}])

        self.assertIn("Fallback mode is active", result)

    def test_generate_endpoint_rejects_missing_messages(self):
        loaded = load_model_service_with_mocks()
        client = loaded["module"].app.test_client()

        response = client.post("/generate", json={})

        self.assertEqual(response.status_code, 400)

    def test_generate_endpoint_returns_model_result(self):
        loaded = load_model_service_with_mocks()
        module = loaded["module"]
        client = module.app.test_client()

        with patch.object(module, "generate_once", return_value="ok") as generate_mock:
            response = client.post("/generate", json={"messages": [{"role": "user", "content": "hi"}]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"result": "ok"})
        generate_mock.assert_called_once()

    def test_generate_endpoint_returns_error_payload_on_exception(self):
        loaded = load_model_service_with_mocks()
        module = loaded["module"]
        client = module.app.test_client()

        with patch.object(module, "generate_once", side_effect=RuntimeError("boom")):
            response = client.post("/generate", json={"messages": [{"role": "user", "content": "hi"}]})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "boom"})

    def test_health_reports_ok_and_fallback_states(self):
        loaded = load_model_service_with_mocks()
        ok_client = loaded["module"].app.test_client()
        fallback_loaded = load_model_service_with_mocks(model_load_error=RuntimeError("offline"))
        fallback_client = fallback_loaded["module"].app.test_client()

        self.assertEqual(ok_client.get("/health").get_json()["status"], "ok")
        fallback_payload = fallback_client.get("/health").get_json()
        self.assertEqual(fallback_payload["status"], "fallback")
        self.assertEqual(fallback_payload["model_load_error"], "offline")

    def test_main_entrypoint_starts_server(self):
        fake_torch = types.ModuleType("torch")
        fake_torch.bfloat16 = "bfloat16"
        fake_torch.float32 = "float32"
        fake_torch.ones_like = lambda tensor: tensor
        fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)

        fake_transformers = types.ModuleType("transformers")

        class FakeBitsAndBytesConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        tokenizer = Mock()
        tokenizer.pad_token_id = 0
        tokenizer.eos_token = "<eos>"
        fake_transformers.AutoTokenizer = types.SimpleNamespace(from_pretrained=Mock(return_value=tokenizer))
        fake_transformers.AutoModelForCausalLM = types.SimpleNamespace(from_pretrained=Mock(return_value=Mock()))
        fake_transformers.BitsAndBytesConfig = FakeBitsAndBytesConfig

        fake_peft = types.ModuleType("peft")
        fake_peft.PeftModel = types.SimpleNamespace(from_pretrained=Mock(return_value=Mock()))

        original_modules = {
            name: sys.modules.get(name)
            for name in ("torch", "transformers", "peft")
        }
        sys.modules["torch"] = fake_torch
        sys.modules["transformers"] = fake_transformers
        sys.modules["peft"] = fake_peft

        try:
            with patch("flask.app.Flask.run") as run_mock, patch("builtins.print") as print_mock:
                runpy.run_module("model_service", run_name="__main__")
        finally:
            for name, original in original_modules.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

        run_mock.assert_called_once_with(host="0.0.0.0", port=9001)
        print_mock.assert_any_call("Model service ready on port 9001.", flush=True)


if __name__ == "__main__":
    unittest.main()