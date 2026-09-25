# Context vault

APEX can write a Markdown copy of selected personal context to one local folder. APEX remains the source of truth: editing a generated note in Obsidian or another app does not change the record in APEX. Export is disabled by default, with no scopes or records selected.

A scope is a named selection inside the vault. Use separate scopes when different readers need different context. Each enabled scope has its own index and any eligible entity and record notes. Its links still work when the folder is copied on its own.

## Set up a vault

1. Choose an absolute local path for the vault root. If you want Google Drive to sync it, choose a folder that [Drive for desktop](https://support.google.com/drive/answer/13401938?hl=en) syncs. Add that path as `APEX_CONTEXT_VAULT_PATH` in `.env`, then restart APEX. The destination is a machine-specific setting; scope selections stay in Runtime Settings. Before changing an existing destination, review its enabled scopes: APEX can publish them at the new path when it starts.
2. In Cortex → Context → Vault, create a scope and select the entities or individual records it may export. Exclude individual records where needed. Selecting an entity includes current records where it is the subject or object, including future qualifying records. It does not pull in neighboring entities' other records.
3. Review the preview before saving and enabling the scope. In Cortex → Context → Records, the **Sensitive record** control marks a record as sensitive. Keep **Include sensitive** off unless that scope should receive sensitive records. APEX asks for another preview when a change broadens what an enabled scope can share.
4. Enable export and select **Refresh now**. Check the destination, selected scope, counts, pending changes, last success, and any error in Vault status. A successful APEX status means the local files were published; check the sync app separately before treating them as available elsewhere.

Only active production records without a pending challenge qualify. Conflicting, superseded, and retracted records, pending proposals, raw reports, conversations, and original source evidence do not appear as exported notes. An accepted claim derived from an external report can qualify and retains limited source attribution. Each scope must opt in separately to sensitive records. See [Configuration](configuration.md#context-vault-selection) for the selection fields and [Privacy](privacy.md#personal-context) for what leaves the local database.

## Read or share the notes

The root `index.md` links to each enabled scope. Generated files use stable IDs in their paths:

```text
index.md
scopes/<scope-id>/index.md
scopes/<scope-id>/entities/<entity-id>.md
scopes/<scope-id>/records/<record-id>.md
```

Open the root folder as an Obsidian vault to browse the notes and their ordinary Markdown links; no Obsidian plugin is required. A scope folder can also be opened or copied by itself. Display names can change without changing the ID-based paths. APEX regenerates edited files at paths it owns, so keep handwritten notes outside the generated paths. It leaves handwritten files and `.obsidian/` alone and refuses to overwrite an unowned file that collides with a generated path.

Before saving a selection, preview lists the generated files under that scope and the shared root `index.md`, marking each as added, updated, or removed compared with the last successful local export. The root index appears when adding, removing, or renaming a scope changes its links. A new scope is shown as additions; when no successful export exists, the preview compares against an empty projection. A preview while export is disabled still shows the projection that would be published if export were enabled. The comparison uses path and content hashes stored in APEX's local database. It does not inspect the destination folder or report whether Drive or another service has synced or indexed the notes.

To use a synced scope with an AI app, first confirm its notes appear in Google Drive. Connect the app to the same Drive account, then ask it to find a distinct fact from a selected record and check the cited source against the note. [Gemini's Google Workspace connection](https://support.google.com/gemini/answer/15229592?hl=en) and [Claude's Google Drive connector](https://support.claude.com/en/articles/10166901-use-google-workspace-connectors) are examples. Some apps offer both a file picker and connector search; test them separately if a picker cannot select a Markdown file. Do not assume the app follows links to other notes or that choosing one folder restricts all of its Drive searches. Check the app's permissions and source controls before sharing real context.

Sharing the vault root can expose its index, other accessible scopes, and handwritten content. Sharing one scope folder keeps its generated links within that scope, but Drive permissions and each AI app's retrieval rules decide what a recipient can actually access. APEX does not manage those external permissions.

## Refresh, recover, and clean up

APEX refreshes enabled scopes after relevant saved knowledge or selection changes and reconciles them when the backend starts. Use **Refresh now** if you want to publish immediately or retry after a failure. Vault status shows whether the local export is dirty, refreshing, or complete, along with the last attempt, last success, and a sanitized error. If the destination is unavailable or a generated path collides with an unowned file, resolve the destination or collision and refresh again. APEX keeps unfinished work for a later retry. Drive synchronization and an AI app's indexing can finish later than the local export.

Disabling export stops updates and leaves generated files in place. To remove APEX-managed copies, disable export first and select **Remove generated copies**. This removes only tracked files at the currently configured destination; it does not recursively delete that folder. Removing a record from the effective selection while export stays enabled removes its managed note on refresh.

Changing `APEX_CONTEXT_VAULT_PATH` leaves copies at the previous root, which Vault status lists as a retained destination. If you want to clear the old root, disable export and remove its generated copies before changing the path. If you already changed it, point `APEX_CONTEXT_VAULT_PATH` back to the old root while export is disabled, restart APEX, run `uv run apex context vault remove`, then restore the new path and restart. Check both folders and Drive after cleanup. Files or answers already copied, indexed, downloaded, or retained by another service may remain there.

Demo mode and the development sandbox can inspect vault information but cannot publish or remove production vault files. The [CLI](cli.md#commands) and [API](api.md#sensitivity-and-context-vault-preview) expose the same local status, preview, refresh, and removal operations for scripted use.

## Check a new setup

Use synthetic accepted records before syncing personal context:

1. Create two distinct, non-sensitive test records in Cortex → Context → Records. If either needs review, accept it before export. Put them in separate scopes, preview each scope, and confirm it contains only the intended record. Enable export and check that each scope has its own index and record note.
2. Open the root in Obsidian. Follow the index links and inspect Graph view. Rename a scope and refresh; its ID-based paths should stay stable. Add a handwritten note and a file under `.obsidian/`, then refresh again; both should remain. An edit to an APEX-owned note should be regenerated.
3. Confirm the notes appear in Drive after its sync completes. Ask a connected AI app for a fact and source reference in one record. Change that record in APEX, wait for local refresh and Drive sync, then ask again in a fresh chat. Retract it and check that the managed note disappears while the other scope remains usable. Test broader folder discovery separately from selecting a single note.

If an app cannot find or read a Markdown note, record the app, account type, selection method, and failure before relying on that route. Local success in APEX does not establish that Drive or the AI app has processed the latest files.
