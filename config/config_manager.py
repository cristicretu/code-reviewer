import os
from loguru import logger
from dynaconf import Dynaconf
from dotenv import load_dotenv

load_dotenv()

profile = os.getenv("DYNACONF_APP_PROFILE")

if profile is None:
    logger.critical("DYNACONF_APP_PROFILE environment variable is not set")
    raise ValueError("Project env not set")

logger.info(f"Initializing application with configuration profile: {profile}")

_settings = Dynaconf(
    envvar_prefix="DYNACONF",
    settings_files=[
        'config/config.yaml',
        f'config/config.{profile}.yaml',
        f'config/.secrets.{profile}.yaml'
    ],
    load_dotenv=True,
)

class SettingsWrapper:
    def __getattr__(self, name):
        value = getattr(_settings, name)
        if value is None:
            raise ValueError(f"Required setting '{name}' is not configured")
        return value

settings = SettingsWrapper()
