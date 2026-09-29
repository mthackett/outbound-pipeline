import os
import unittest
from job_pipeline.logger import (
    is_logging_enabled,
    set_logging_enabled,
    log_cli,
    log_timed_action,
    log_startup,
    log_action,
    log_sheets,
    log_drive,
    log_llm
)
from job_pipeline.domain.services import PipelineConfigService


class TestCliLogger(unittest.TestCase):
    def setUp(self):
        self.test_cfg_path = "test_pipeline_config_logger.json"
        if os.path.exists(self.test_cfg_path):
            os.remove(self.test_cfg_path)
        # Clear env overrides
        os.environ.pop("ENABLE_CLI_LOGGING", None)
        os.environ.pop("CLI_LOGGING", None)
        os.environ.pop("PIPELINE_CONFIG_PATH", None)

    def tearDown(self):
        if os.path.exists(self.test_cfg_path):
            os.remove(self.test_cfg_path)
        os.environ.pop("ENABLE_CLI_LOGGING", None)
        os.environ.pop("CLI_LOGGING", None)
        os.environ.pop("PIPELINE_CONFIG_PATH", None)

    def test_default_logging_enabled(self):
        os.environ["PIPELINE_CONFIG_PATH"] = self.test_cfg_path
        self.assertTrue(PipelineConfigService.is_cli_logging_enabled(self.test_cfg_path))
        self.assertTrue(is_logging_enabled(force_refresh=True))

    def test_toggle_logging_in_config(self):
        os.environ["PIPELINE_CONFIG_PATH"] = self.test_cfg_path
        # Disable
        PipelineConfigService.set_cli_logging(False, self.test_cfg_path)
        self.assertFalse(PipelineConfigService.is_cli_logging_enabled(self.test_cfg_path))
        self.assertFalse(is_logging_enabled(force_refresh=True))

        # Re-enable
        PipelineConfigService.set_cli_logging(True, self.test_cfg_path)
        self.assertTrue(PipelineConfigService.is_cli_logging_enabled(self.test_cfg_path))
        self.assertTrue(is_logging_enabled(force_refresh=True))

    def test_env_override_takes_precedence(self):
        os.environ["PIPELINE_CONFIG_PATH"] = self.test_cfg_path
        PipelineConfigService.set_cli_logging(True, self.test_cfg_path)

        os.environ["ENABLE_CLI_LOGGING"] = "0"
        self.assertFalse(is_logging_enabled(force_refresh=True))

        os.environ["ENABLE_CLI_LOGGING"] = "1"
        self.assertTrue(is_logging_enabled(force_refresh=True))

    def test_log_functions_execute_without_error(self):
        # Should execute cleanly whether logging is True or False
        set_logging_enabled(True)
        log_startup("Test startup action")
        log_action("Test generic action")
        log_sheets("Test sheets action")
        log_drive("Test drive action")
        log_llm("Test LLM action")

        with log_timed_action("Test timed block", tag="TEST"):
            pass

        set_logging_enabled(False)
        log_startup("Should not be printed")


if __name__ == "__main__":
    unittest.main()
