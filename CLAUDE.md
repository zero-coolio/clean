# CleanMedia

Safety-critical TV/movie organizer. It renames and deletes files on a real media
volume, unattended, from a launchd/fswatch watcher. Assume every change can
destroy data until proven otherwise.

## Test against original release names, never post-clean names

**Rule (Steve, 2026-09-18): tests use the names trackers actually delivered.**

Feeding the parser a name CleanMedia produced proves nothing about its real job:
that name is already in our own dialect, so it parses trivially and the test is
theatre. The names that break things are the ones that arrive from outside.

Two checked-in corpora, both sampled from the undo journals on the media volume
(`/Volumes/Seagate/seagate-qBittorrent/.clean-tv-journal-*.jsonl`):

| fixture | source | question it answers |
| --- | --- | --- |
| `tests/fixtures/original_release_names.json` | journal `src` | can we read what trackers deliver? |
| `tests/fixtures/emitted_names.json` | journal `dst` | can we read back what we wrote? |

The first excludes post-clean names deliberately. The second exists because a
name we emit and cannot re-parse freezes that file forever (CLEAN-11).

When adding parser cases, take real names from the journals or the volume. Do
not invent plausible-looking ones; invented names encode what you already think
the format is, which is exactly the assumption under test.

### Floors must be near the measured value

`MIN_PARSE_RATE` is pinned just under the measured rate. A floor far below the
real number is not a test: it passes while the parser rots. Raise it when the
parser improves; never lower it to make a failure go away.

### Known-bad lists must be explicit and pruned

`KNOWN_BAD` in `test_emitted_names_roundtrip.py` lists every name that still
fails, by name, with the reason. One test asserts it has not grown; another
asserts every entry still fails, so a landed fix forces its removal instead of
letting the list rot into a lie.

## Running clean from an agent shell

TVMaze is unreachable without an explicit cert bundle, and `_search` swallows
every exception and returns `[]`, so failures look like "no results" rather than
errors. A `--commit` run without this resolves every show with NO year and
creates duplicate folders (a second `Gotham/` beside `Gotham (2014)`).

```bash
SSL_CERT_FILE="$(python3 -c 'import certifi;print(certifi.where())')" \
  python3 -m src.Main -d /Volumes/Seagate/seagate-qBittorrent
```

## Preview at the library root, never at one show folder

A show-scoped dry run nests destinations and hides interactions with the rest of
the library. Always `-d /Volumes/Seagate/seagate-qBittorrent`, and read the
whole preview before `--commit`. Budget ~7 minutes: it is one TVMaze call per
file.

## Stop the watcher before repairing

`launchctl unload ~/Library/LaunchAgents/com.nulleffect.clean-tv-watcher.plist`.
The watcher runs `src.Main --commit` from the **working tree**, so an
uncommitted change is live the moment fswatch fires. `pkill` will not stop it.

## Deletes

`safe_delete` uses `send2trash`, which resolves to its `mac.legacy` backend
here. That backend does not write Finder put-back metadata, so **"Put Back" is
never available** for anything CleanMedia trashes, and `undo_from_journal`
cannot restore them either (it logs `CANNOT UNDO TRASH`). Recovery is manual:
drag the files out of the Trash, then re-file them from the journal, which is
the only record of where each one belongs.
