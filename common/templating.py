from __future__ import annotations

import hashlib

# (package, directory, version) -> Jinja2-окружение для ресурсов
_resource_envs: dict[tuple[str, str, str], object] = {}


class TemplateSet:
    """Набор Jinja-шаблонов из package resources.

    Читает *.md и *.j2 рекурсивно из каталога пакета и рендерит их общим
    окружением. Версия считается по содержимому, поэтому в рабочей копии
    правка шаблона подхватывается без перезапуска, а в wheel не зависит
    от времени изменения файлов.
    """

    def __init__(self, package: str, directory: str) -> None:
        self.package = package
        self.directory = directory

    def _root(self):
        from importlib.resources import files

        return files(self.package).joinpath(self.directory)

    @staticmethod
    def _child(node, name: str):
        """Traversable по относительному POSIX-пути."""
        for part in name.split("/"):
            node = node.joinpath(part)
        return node

    def _collect(self, node, prefix: str = "") -> dict[str, str]:
        texts: dict[str, str] = {}
        for entry in node.iterdir():
            name = f"{prefix}{entry.name}"
            if entry.is_dir():
                texts.update(self._collect(entry, f"{name}/"))
            elif entry.is_file() and entry.name.endswith((".md", ".j2")):
                texts[name] = entry.read_text(encoding="utf-8")
        return texts

    def snapshot(self) -> tuple[str, dict[str, str]]:
        """(версия, {относительный путь: текст}) на момент вызова."""
        texts = self._collect(self._root())
        digest = hashlib.sha256()
        for name in sorted(texts):
            digest.update(name.encode("utf-8"))
            digest.update(texts[name].encode("utf-8"))
        return digest.hexdigest()[:8], texts

    def names(self) -> list[str]:
        """Относительные пути шаблонов набора (отсортированы)."""
        return sorted(self.snapshot()[1])

    def version(self) -> str:
        """Короткий SHA-256 содержимого набора шаблонов."""
        return self.snapshot()[0]

    def read_text(self, name: str) -> str:
        """Текст любого ресурса набора, включая manifest.toml."""
        return self._child(self._root(), name).read_text(encoding="utf-8")

    def render(self, name: str, **context) -> str:
        """Рендерит шаблон по имени с подстановкой контекста."""
        version, texts = self.snapshot()
        key = (self.package, self.directory, version)
        env = _resource_envs.get(key)
        if env is None:
            from jinja2 import DictLoader, Environment, StrictUndefined

            env = Environment(
                loader=DictLoader(texts),
                undefined=StrictUndefined,
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=True,
            )
            _resource_envs[key] = env
        return env.get_template(name).render(**context)


def reset() -> None:
    """Сброс кэша окружений (тесты: правка шаблонов на лету)."""
    _resource_envs.clear()
