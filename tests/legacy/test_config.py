from landlord.legacy.config import LandlordConfig


class TestConfig:
    def test_defaults(self):
        config = LandlordConfig()
        assert config.landlord_model == "claude-sonnet-4-20250514"
        assert config.tenant_model is None
        assert config.output_dir == "./output"
        assert config.max_retries == 3
        assert config.verbose is False
        assert config.auto_approve is False

    def test_effective_tenant_model_defaults_to_landlord(self):
        config = LandlordConfig()
        assert config.effective_tenant_model == "claude-sonnet-4-20250514"

    def test_effective_tenant_model_when_set(self):
        config = LandlordConfig(tenant_model="gpt-4o")
        assert config.effective_tenant_model == "gpt-4o"

    def test_load_from_yaml(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            "landlord_model: claude-opus-4-20250514\n"
            "max_retries: 5\n"
            "verbose: true\n"
        )
        config = LandlordConfig.load(config_path=str(yaml_file))
        assert config.landlord_model == "claude-opus-4-20250514"
        assert config.max_retries == 5
        assert config.verbose is True

    def test_cli_overrides_yaml(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("landlord_model: claude-opus-4-20250514\nmax_retries: 5\n")
        config = LandlordConfig.load(
            config_path=str(yaml_file),
            landlord_model="gpt-4o",
        )
        assert config.landlord_model == "gpt-4o"
        assert config.max_retries == 5

    def test_missing_yaml_uses_defaults(self):
        config = LandlordConfig.load(config_path="/nonexistent/config.yaml")
        assert config.landlord_model == "claude-sonnet-4-20250514"

    def test_unknown_yaml_keys_ignored(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("landlord_model: gpt-4o\nunknown_key: whatever\n")
        config = LandlordConfig.load(config_path=str(yaml_file))
        assert config.landlord_model == "gpt-4o"
