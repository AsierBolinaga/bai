import yaml

with open("config/motors_config.yaml", "r", encoding="utf-8") as f:
    motors_config = yaml.safe_load(f)