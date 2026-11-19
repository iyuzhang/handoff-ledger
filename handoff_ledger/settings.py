import os
from dataclasses import dataclass, field
from pathlib import Path

from httpx import URL


LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    allowed_hosts: tuple[str, ...] = LOCAL_HOSTS
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    json_mode: bool = True
    timeout: int = 90

    @property
    def database_path(self) -> Path:
        return self.data_dir / "handoff-ledger.sqlite3"

    @property
    def model_configured(self) -> bool:
        return bool(self.base_url and self.model)

    @classmethod
    def from_env(cls) -> "Settings":
        """Loads and validates the service configuration."""
        default_data_home = Path.home() / ".local" / "share"
        data_home = Path(os.environ.get("XDG_DATA_HOME") or default_data_home)
        data_dir = Path(os.environ.get("HANDOFF_DATA_DIR") or data_home / "handoff-ledger").expanduser()
        extra_hosts = tuple(filter(None, (host.strip() for host in os.getenv("HANDOFF_ALLOWED_HOSTS", "").split(","))))
        if any("*" in host or "/" in host or (":" in host and host != "[::1]") for host in extra_hosts):
            raise ValueError("HANDOFF_ALLOWED_HOSTS must contain exact hostnames without ports.")

        base_url = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
        model = os.getenv("LLM_MODEL", "").strip()
        if bool(base_url) != bool(model):
            raise ValueError("Set both LLM_BASE_URL and LLM_MODEL for AI generation.")
        if base_url:
            url = URL(base_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.host
                or url.userinfo
                or url.query
                or url.fragment
            ):
                raise ValueError("LLM_BASE_URL must be an HTTP(S) endpoint without credentials or query parameters.")

        timeout_text = os.getenv("LLM_TIMEOUT_SECONDS", "90")
        if not timeout_text.isdecimal() or not 5 <= int(timeout_text) <= 180:
            raise ValueError("LLM_TIMEOUT_SECONDS must be an integer from 5 to 180.")
        json_mode = os.getenv("LLM_JSON_MODE", "1")
        if json_mode not in {"0", "1"}:
            raise ValueError("LLM_JSON_MODE must be 0 or 1.")
        return cls(
            data_dir=data_dir,
            allowed_hosts=LOCAL_HOSTS + extra_hosts,
            base_url=base_url,
            model=model,
            api_key=os.getenv("LLM_API_KEY", "").strip(),
            json_mode=json_mode == "1",
            timeout=int(timeout_text),
        )
