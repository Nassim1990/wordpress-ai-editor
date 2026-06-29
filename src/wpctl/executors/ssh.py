"""SSH / WP-CLI executor.

Runs WP-CLI over SSH using the site's resolved key. paramiko is an optional
dependency, imported lazily so the package imports without it. Command building
uses shlex.quote on every argument; WP-CLI is always invoked with --path and a
fixed binary so nothing is shell-interpolated from caller input.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from ..models import Site
from ..secrets import SecretResolver


class WPCLIError(RuntimeError):
    def __init__(self, cmd: str, code: int, stderr: str) -> None:
        super().__init__(f"wp-cli exited {code}: {stderr.strip()}")
        self.cmd = cmd
        self.code = code
        self.stderr = stderr


@dataclass
class CommandResult:
    code: int
    stdout: str
    stderr: str


class SSHRunner:
    def __init__(self, secrets: SecretResolver) -> None:
        self._secrets = secrets

    def _connect(self, site: Site):
        try:
            import io

            import paramiko
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pip install 'wpctl[ssh]' to use SSH/WP-CLI tools") from e
        if not (site.ssh_host and site.ssh_user and site.ssh_key_ref):
            raise RuntimeError(f"site {site.slug} is missing SSH configuration")
        key_material = self._secrets.resolve(site.ssh_key_ref)
        pkey = paramiko.RSAKey.from_private_key(io.StringIO(key_material))
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.load_system_host_keys()
        client.connect(hostname=site.ssh_host, port=site.ssh_port,
                       username=site.ssh_user, pkey=pkey, timeout=20)
        return client

    def run(self, site: Site, argv: list[str]) -> CommandResult:
        """Run a raw command (argv list). Caller is responsible for tier gating."""
        cmd = " ".join(shlex.quote(a) for a in argv)
        client = self._connect(site)
        try:
            _, stdout, stderr = client.exec_command(cmd, timeout=120)
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            code = stdout.channel.recv_exit_status()
            return CommandResult(code, out, err)
        finally:
            client.close()

    def wp(self, site: Site, args: list[str], allow_root: bool = True) -> str:
        """Run a `wp` subcommand against the site, return stdout. Raises WPCLIError."""
        argv = ["wp", "--path=" + site.wp_path]
        if allow_root:
            argv.append("--allow-root")
        argv += args
        res = self.run(site, argv)
        if res.code != 0:
            raise WPCLIError(" ".join(args), res.code, res.stderr)
        return res.stdout
