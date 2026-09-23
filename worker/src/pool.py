import threading

from src.config import settings
from src.providers.base import GenerationResult
from src.providers.mock import MockProvider


def build_provider(name: str):
    if settings.provider_mode == "mock":
        return MockProvider(settings.media_path, settings.sessions_path, name=name)
    if name == "chatgpt":
        from src.providers.chatgpt import ChatGPTProvider

        return ChatGPTProvider(settings.media_path, settings.sessions_path)
    raise ValueError("provider {} has no real implementation yet".format(name))


class BrowserPool:
    """Owns one browser session per provider, serialised by a lock.

    Two requests must never share a page, so every provider gets its own lock and
    a job waits rather than interleaving.
    """

    def __init__(self):
        self._providers = {}
        self._locks = {}
        self._errors = {}

    def start(self):
        for name in settings.providers:
            try:
                provider = build_provider(name)
                provider.start()
                self._providers[name] = provider
                self._locks[name] = threading.Lock()
            except Exception as exc:
                self._errors[name] = "{}: {}".format(type(exc).__name__, exc)

    def stop(self):
        for provider in self._providers.values():
            try:
                provider.stop()
            except Exception:
                pass
        self._providers.clear()

    def execute(self, provider_name: str, feature: str, payload: dict,
                thread_url: str = None) -> GenerationResult:
        provider = self._providers.get(provider_name)
        if provider is None:
            return GenerationResult.failure(
                "provider {} unavailable: {}".format(
                    provider_name, self._errors.get(provider_name, "not enabled on this worker")
                )
            )
        if not provider.supports(feature):
            return GenerationResult.failure(
                "provider {} does not support {}".format(provider_name, feature)
            )

        with self._locks[provider_name]:
            try:
                if feature == "chat":
                    return provider.chat(
                        payload.get("message", ""), payload.get("history"), thread_url
                    )
                if feature == "image":
                    return provider.generate_image(
                        payload.get("prompt", ""), payload.get("reference_filename"), thread_url
                    )
                if feature == "video_script":
                    return provider.generate_video_script(
                        payload.get("filename", ""), int(payload.get("duration", 5)), thread_url
                    )
            except Exception as exc:
                return GenerationResult.failure("{}: {}".format(type(exc).__name__, exc))
        return GenerationResult.failure("unknown feature {}".format(feature))

    def status(self) -> dict:
        out = {}
        for name in settings.providers:
            provider = self._providers.get(name)
            out[name] = {
                "ready": provider is not None,
                "features": sorted(f.value for f in provider.supported_features) if provider else [],
                "error": self._errors.get(name),
            }
        return out
