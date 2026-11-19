# Operations

## Runtime configuration

Set variables in the process environment. With Docker Compose, set the model and host variables in your shell or in a private `.env` file beside `compose.yaml`, then start or recreate the container.

| Variable | Purpose |
| --- | --- |
| `HANDOFF_DATA_DIR` | SQLite directory. Defaults to `$XDG_DATA_HOME/handoff-ledger` when that base directory is set, otherwise `~/.local/share/handoff-ledger`. The container uses the `ledger-data` volume mounted at `/data`. |
| `HANDOFF_ALLOWED_HOSTS` | Comma-separated additional HTTP host names. The built-in names are `localhost`, `127.0.0.1`, and `[::1]`. |
| `LLM_BASE_URL` | OpenAI-compatible API base, typically ending in `/v1`. The server adds the Chat Completions path. |
| `LLM_MODEL` | Model identifier expected by your provider. Set with `LLM_BASE_URL` to enable drafting. |
| `LLM_API_KEY` | Server-side provider credential. Optional for an unauthenticated endpoint. |
| `LLM_JSON_MODE` | Set to `0` if the provider rejects the `json_object` response format. |
| `LLM_TIMEOUT_SECONDS` | Provider request timeout in seconds, from 5 to 180. Defaults to 90. |

The container binds internally to `0.0.0.0:8080` and Compose publishes it to `127.0.0.1:8080` on the host. A native install binds to `127.0.0.1:8080` by default. Use `handoff-ledger serve --port PORT` to change the native port.

## Access and source data

Run one app process per data directory. The app is intended for a single trusted user and has no built-in authentication. Keep it on loopback. For a private remote machine, forward the loopback listener through SSH.

```sh
ssh -L 8080:127.0.0.1:8080 your-server
```

If you use a reverse proxy, require authentication and TLS at the proxy and block direct access to the app port. Add the proxy's public host name to `HANDOFF_ALLOWED_HOSTS` if forwarded in the HTTP Host header. An allowed host name does not authenticate a user.

Sources and past revisions persist in the workspace database, including archived sources. JSON and Markdown exports can contain copies of source excerpts. Treat both exports and backups as confidential when a workspace includes private material. Model requests contain the handoff title, goal, and full text of selected source revisions. Keep API keys outside source documents and version control.

## Backup and restore

Use the backup command to take a consistent SQLite copy while the service is running. The same `HANDOFF_DATA_DIR` used by the service must be in effect when invoking the command. Choose a new output filename in an existing directory.

```sh
handoff-ledger backup "handoff-$(date +%Y%m%d-%H%M%S).sqlite3"
```

With Docker Compose, create the copy inside the container and copy it to the host.

```sh
backup_file="handoff-$(date +%Y%m%d-%H%M%S).sqlite3"
docker compose exec -T ledger handoff-ledger backup "/tmp/$backup_file"
docker compose cp "ledger:/tmp/$backup_file" "./$backup_file"
```

Store backups away from the original workspace. To check a backup, copy it as `handoff-ledger.sqlite3` into a new directory and start a separate instance against that directory.

```sh
restore_dir="$(mktemp -d)"
cp ./your-backup.sqlite3 "$restore_dir/handoff-ledger.sqlite3"
HANDOFF_DATA_DIR="$restore_dir" handoff-ledger serve --port 8081
```

Open [http://127.0.0.1:8081](http://127.0.0.1:8081) and inspect a project, a source revision, and a sealed record. To restore it as your primary workspace, stop the primary instance and point it to the restored directory. Retain the previous directory for rollback. For Compose, use a new named volume or bind mount for the restored directory and make sure UID 10001 can write to it.

## Upgrades and troubleshooting

Back up first. Install the new wheel or update the checkout to the new release tag. For Compose, run `docker compose up -d --build` after updating the checkout. Keep the data volume attached across releases. Then check the app and inspect an existing record.

| Symptom | Check |
| --- | --- |
| The browser cannot load the workspace | Confirm the process is running and visit `/api/health` on the configured listener. A port conflict can be resolved with `--port` or a different Compose host port. |
| An HTTP request rejects the host | Use the loopback address or add the intended hostname to `HANDOFF_ALLOWED_HOSTS` and restart. |
| Draft generation is unavailable | Ensure both model variables are set on the server and restart. |
| Generation ends with a provider error | Verify the URL, model name, and credential. For a gateway that rejects JSON mode, select the same sources and try again after setting `LLM_JSON_MODE=0`. |
| Generation rejects the source selection | A generation request accepts up to 16 sources and 80,000 characters across them. Narrow the selection or create a manual draft. |
| Filesystem permission errors in a container | Confirm the mounted SQLite directory is writable by the container's unprivileged user with UID 10001. |

The running service publishes its API schema at `/api/openapi.json`.
