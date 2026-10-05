"""Build and check an isolated production-profile fixture for import smoke runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

FIXTURE_TEXT = "Data import rehearsal preserves this production record."
AUDIO_BYTES = b"RIFF\x00\x00\x00\x00WAVEapex-import-audio-fixture"
FASTEMBED_FIXTURE_BYTES = b"F" * (16 * 1024 * 1024)
EXPECTED_CREDENTIAL = "fixture-only-not-a-real-secret"
MICROSOFT_CACHE_TEXT = json.dumps({"FixtureAccessToken": [{"secret": "synthetic-only"}]}, separators=(",", ":"))


def _synthetic_microsoft_cache_path(profile: Path) -> Path:
    return profile.parent / "local-app-data" / "APEX" / "auth" / "microsoft_todo_token_cache.bin"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def managed_fingerprint(profile: Path) -> str:
    """Hash fixture-managed files while ignoring transient SQLite sidecars."""
    files = []
    for path in sorted(profile.rglob("*")):
        if not path.is_file() or path.name.endswith(("-wal", "-shm", "-journal")) or path.name == ".apex-host.lock":
            continue
        files.append((path.relative_to(profile).as_posix(), _hash(path)))
    canonical = json.dumps(files, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def seed(profile: Path) -> dict[str, Any]:
    profile.mkdir(parents=True, exist_ok=True)
    if any(profile.iterdir()):
        raise RuntimeError("fixture destination must be empty")

    # Select the fixture root before importing modules whose database paths are
    # resolved at import time. The same profile layout is used by source runs.
    os.environ["APEX_DATA_DIR"] = str(profile.resolve())
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    local_app_data = profile.parent / "local-app-data"
    os.environ["LOCALAPPDATA"] = str(local_app_data.resolve())

    from core import database
    from core.actions.models import ActionProposal
    from core.actions.store import ActionStore
    from core.activity.models import ActivityFinding, ActivityReportContent
    from core.activity.store import ActivityStore
    from core.briefings.models import (
        BUILTIN_BRIEFING_PROFILES,
        BriefingCoverage,
        BriefingDraft,
        BriefingEvidence,
        BriefingGenerationConfiguration,
        BriefingGenerationRequest,
        BriefingItemDraft,
        BriefingModelConfiguration,
        BriefingSectionDraft,
    )
    from core.briefings.service import BriefingGenerationOutput, BriefingService
    from core.briefings.store import BriefingSessionStore
    from core.context_vault.publisher import ContextVaultPublicationStateStore
    from core.conversations.store import ConversationStore
    from core.knowledge.store import KnowledgeStore
    from core.runs.coordinator import CortexRunCoordinator
    from core.runs.models import RunLimitSnapshot
    from core.runs.service import RunService
    from core.runs.store import RunStore
    from core.retrieval.store import RetrievalStore
    from msal_extensions import build_encrypted_persistence

    db_path = profile / "apex_memory.db"
    with sqlite3.connect(db_path) as connection:
        database.initialize_db(connection=connection)

    conversations = ConversationStore(db_path)
    conversations.initialize()
    runs = RunStore(db_path)
    runs.initialize()
    briefings = BriefingSessionStore(db_path)
    briefings.initialize()
    knowledge = KnowledgeStore(db_path)
    knowledge.initialize()
    actions = ActionStore(db_path)
    actions.initialize()
    reports = ActivityStore(db_path)
    reports.initialize()
    retrieval = RetrievalStore(db_path)
    retrieval.initialize()

    # A normal, completed production Cortex conversation with a retained turn.
    conversation_id = uuid4()
    conversations.create(
        conversation_id=conversation_id,
        title="Import preservation rehearsal",
        partition="production",
        origin="hud",
        agent="apex",
        selected_tool_names=[],
        tool_profile_id=None,
    )
    user_id, agent_id = uuid4(), uuid4()
    conversations.begin_turn(
        conversation_id=conversation_id,
        partition="production",
        user_id=user_id,
        agent_id=agent_id,
        parent_id=None,
        prompt="Keep this conversation through import.",
        agent="apex",
        request_metadata={"model_id": "fixture/local"},
        selected_tool_names=[],
        tool_profile_id=None,
        history_limit=20,
    )
    conversations.finalize(
        conversation_id=conversation_id,
        agent_id=agent_id,
        answer=FIXTURE_TEXT,
        status="completed",
        response_metadata={"fixture": "data_import_rehearsal"},
    )

    # Keep a canonical knowledge record, its source, and the durable action
    # effect that created it. The associated action remains outcome_unknown.
    now = datetime.now(timezone.utc)
    action_id = str(uuid4())
    proposal = ActionProposal(
        agent_key="apex",
        capability_name="capture_personal_context",
        arguments={"text": "Fixture action must never be replayed."},
        target="local personal context",
        risk="write",
        summary="Preserve an import rehearsal action",
        proposed_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    action = actions.propose(proposal, actor="fixture", action_id=action_id)
    action = actions.approve(action_id, actor="fixture", now=now, expected_version=action.version)
    action = actions.claim_execution(action_id, actor="fixture", now=now, expected_version=action.version)
    actions.transition(
        action_id,
        expected_statuses=("executing",),
        to_status="outcome_unknown",
        actor="fixture",
        result_code="fixture_external_outcome_unknown",
        evidence={"replay": "must_not_run"},
        now=now,
        expected_version=action.version,
    )
    record, source, _outcome = knowledge.apply_capture(
        action_id=action_id,
        partition="production",
        source_kind="manual",
        locator="data-import-rehearsal",
        original_text="The fixture evidence is a local operator statement.",
        kind="decision",
        text="Preserve the action effect without replaying it.",
        derivation="direct",
    )

    # Reports are stored as untrusted production intake, separate from accepted
    # personal knowledge.
    report = reports.submit(
        partition="production",
        client_id="import_fixture",
        client_display_name="Import rehearsal",
        principal="operator",
        content=ActivityReportContent(
            submission_key="data-import-rehearsal",
            title="Import rehearsal report",
            task_status="completed",
            outcome="Preserve this received report as report data.",
            findings=[ActivityFinding(title="Fixture finding", text=FIXTURE_TEXT)],
            markdown_body="# Import rehearsal\n\n" + FIXTURE_TEXT,
        ),
    )

    evidence = BriefingEvidence(
        source="news",
        source_id="historical-news-fixture",
        trust="observed",
        comparison_role="historical",
        content="A saved historical News item that current collection no longer produces.",
    )
    request = BriefingGenerationRequest(
        idempotency_key=uuid4(), profile_id="daily", model_id="fixture/local",
    )
    configuration = BriefingGenerationConfiguration(
        profile=BUILTIN_BRIEFING_PROFILES["daily"],
        model=BriefingModelConfiguration(
            model_id=request.model_id,
            provider="demo",
            runtime="demo",
            max_elapsed_seconds=30,
            max_retries=0,
            max_model_turns=1,
            max_tool_calls=1,
            output_token_limit=256,
        ),
        origin=request.origin,
        execution_kind="demo",
    )
    output = BriefingGenerationOutput(
        draft=BriefingDraft(sections=[BriefingSectionDraft(
            title="Historical items",
            items=[BriefingItemDraft(
                category="observation",
                title="Saved historical News",
                body="Keep this older evidence with the briefing artifact.",
                evidence_ids=[evidence.id],
            )],
        )]),
        evidence=[evidence],
        coverage=[BriefingCoverage(source="news", scope="historical", status="complete")],
    )

    def resolve(_request: BriefingGenerationRequest) -> BriefingGenerationConfiguration:
        return configuration

    coordinator = CortexRunCoordinator(RunService(runs), max_workers=1)
    try:
        briefing_service = BriefingService(
            store=briefings,
            conversations=conversations,
            runs=RunService(runs),
            coordinator=coordinator,
            partition_getter=lambda: "production",
            resolve_configuration=resolve,
            execute_generation=lambda *_args: output,
        )
        started = briefing_service.start(request)
        if started.future is None:
            raise RuntimeError("fixture briefing did not start")
        started.future.result(timeout=10)
        session = briefings.mark_presented(started.session.id, "production")
        if session.artifact is None:
            raise RuntimeError("fixture briefing did not save a canonical artifact")
        artifact_sha256 = briefings._speech_artifact_hash(session.artifact.model_dump_json())
        speech_request_id = uuid4()
        briefings.begin_speech_preparation(
            session_id=session.id,
            partition="production",
            artifact_sha256=artifact_sha256,
            request_id=speech_request_id,
            requested_engine="pyttsx3",
            voice_gender="female",
        )
        if not briefings.complete_speech_preparation(
            session_id=session.id,
            partition="production",
            request_id=speech_request_id,
            artifact_sha256=artifact_sha256,
            script_json=json.dumps({"schema_version": 1, "text": "Rehearsal audio."}),
            engine="pyttsx3",
            duration_seconds=1.25,
            chunks=[{"audio": AUDIO_BYTES, "content_type": "audio/wav", "engine": "pyttsx3", "duration_seconds": 1.25}],
        ):
            raise RuntimeError("fixture speech audio did not persist")
    finally:
        coordinator.close(timeout_seconds=5)

    vault_destination = (profile.parent / "external-context-vault").resolve()
    vault_destination.mkdir(parents=True, exist_ok=True)
    (vault_destination / "fixture.md").write_text("External vault fixture\n", encoding="utf-8")
    external_models = (profile.parent / "external-models").resolve()
    external_models.mkdir(parents=True, exist_ok=True)
    (external_models / "llama-server.exe").write_bytes(b"synthetic external model server reference")
    (external_models / "apex-local-models.preset.ini").write_bytes(b"# synthetic fixture preset\n")
    vault_state = ContextVaultPublicationStateStore(db_path)
    vault_state.finish(
        os.path.normcase(str(vault_destination)),
        {"claims/fixture.md": hashlib.sha256(b"owned note").hexdigest()},
    )

    (profile / "config.json").write_text(json.dumps({"fixture": "data_import_rehearsal"}, indent=2) + "\n", encoding="utf-8")
    (profile / "config.local.json").write_text(json.dumps({
        "context_vault": {"path": str(vault_destination)},
        "llama_cpp": {
            "enabled": False,
            "managed": False,
            "executable_path": str(external_models / "llama-server.exe"),
            "preset_path": str(external_models / "apex-local-models.preset.ini"),
        },
        "ollama": {"enabled": False, "host": "http://127.0.0.1:11434"},
    }, indent=2) + "\n", encoding="utf-8")
    (profile / ".env").write_text(
        f"APEX_IMPORT_FIXTURE_SECRET={EXPECTED_CREDENTIAL}\n"
        f"APEX_CONTEXT_VAULT_PATH={vault_destination}\n",
        encoding="utf-8",
    )
    (profile / "credentials.json").write_text(json.dumps({"fixture_token": EXPECTED_CREDENTIAL}), encoding="utf-8")
    for relative, payload in (
        ("weights/fastembed/fixture-model.bin", FASTEMBED_FIXTURE_BYTES),
        ("core/weights/kokoro/fixture-model.bin", b"managed kokoro fixture bytes"),
        ("clients/.market_cache.json", b'{"fixture":"market-cache"}\n'),
    ):
        path = profile / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    # Use actual Windows DPAPI-backed MSAL persistence with synthetic data.
    # This lives outside the source profile, like the operator's same-user cache.
    microsoft_cache_path = _synthetic_microsoft_cache_path(profile)
    microsoft_cache_path.parent.mkdir(parents=True, exist_ok=True)
    persistence = build_encrypted_persistence(str(microsoft_cache_path.resolve()))
    persistence.save(MICROSOFT_CACHE_TEXT)

    for store in (reports, actions, knowledge, retrieval, briefings, runs, conversations):
        close = getattr(store, "close", None)
        if close:
            close()

    return {
        "conversation_id": str(conversation_id),
        "knowledge_record_id": str(record.id),
        "knowledge_source_id": str(source.id),
        "action_id": action_id,
        "report_id": str(report.report.id),
        "briefing_session_id": str(session.id),
        "vault_destination": str(vault_destination),
        "credential_sha256": hashlib.sha256(EXPECTED_CREDENTIAL.encode()).hexdigest(),
        "microsoft_cache_sha256": _hash(microsoft_cache_path),
        "source_fingerprint": managed_fingerprint(profile),
    }


def verify(profile: Path) -> dict[str, Any]:
    db_path = profile / "apex_memory.db"
    if not db_path.is_file():
        raise RuntimeError("fixture database is missing")
    os.environ["APEX_DATA_DIR"] = str(profile.resolve())
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LOCALAPPDATA"] = str((profile.parent / "local-app-data").resolve())
    with sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        conversation = connection.execute(
            "SELECT m.content FROM conversations c JOIN conversation_messages m "
            "ON m.conversation_id=c.id WHERE c.title=? AND m.role='agent' AND m.status='completed'",
            ("Import preservation rehearsal",),
        ).fetchone()
        knowledge = connection.execute(
            "SELECT r.text FROM knowledge_records r WHERE r.text=? AND r.partition='production'",
            ("Preserve the action effect without replaying it.",),
        ).fetchone()
        report = connection.execute(
            "SELECT count(*) FROM activity_reports WHERE submission_key='data-import-rehearsal' AND partition='production'",
        ).fetchone()[0]
        historical_news = connection.execute(
            "SELECT count(*) FROM briefing_sessions s, json_each(s.evidence_json) e "
            "WHERE json_extract(e.value,'$.source')='news' "
            "AND json_extract(e.value,'$.source_id')='historical-news-fixture'",
        ).fetchone()[0]
        audio = connection.execute(
            "SELECT audio_blob FROM briefing_speech_audio_chunks c JOIN briefing_sessions s "
            "ON s.id=c.session_id WHERE s.idempotency_key IN "
            "(SELECT idempotency_key FROM briefing_sessions WHERE json_extract(evidence_json,'$[0].source_id')='historical-news-fixture')",
        ).fetchone()
        unknown_action = connection.execute(
            "SELECT status FROM actions WHERE capability_name='capture_personal_context'",
        ).fetchone()
        audit_events = connection.execute(
            "SELECT count(*) FROM action_events e JOIN actions a ON a.action_id=e.action_id "
            "WHERE a.capability_name='capture_personal_context'",
        ).fetchone()[0]
        effects = connection.execute(
            "SELECT count(*) FROM knowledge_action_effects e JOIN actions a ON a.action_id=e.action_id "
            "WHERE a.capability_name='capture_personal_context'",
        ).fetchone()[0]
        vault = connection.execute(
            "SELECT owned_files_json,last_success_at FROM context_vault_publication_state",
        ).fetchone()
        briefing_row = connection.execute(
            "SELECT id FROM briefing_sessions WHERE json_extract(evidence_json,'$[0].source_id')='historical-news-fixture'",
        ).fetchone()

    if not conversation or FIXTURE_TEXT not in str(conversation[0]):
        raise RuntimeError("canonical conversation did not survive import")
    if not knowledge or report < 1:
        raise RuntimeError("canonical knowledge or received report did not survive import")
    if historical_news < 1:
        raise RuntimeError("saved historical News evidence did not survive import")
    if not audio or bytes(audio[0]) != AUDIO_BYTES:
        raise RuntimeError("saved speech audio bytes did not survive import")
    # Exercise the domain owners after the raw persistence checks. A preserved
    # row must still deserialize as a saved News artifact and produce playable
    # chunks through the briefing reader.
    from core.briefings.store import BriefingSessionStore
    from core.context_vault.publisher import ContextVaultPublicationStateStore
    from uuid import UUID

    briefing_store = BriefingSessionStore(db_path)
    session = briefing_store.get(UUID(str(briefing_row[0])), "production") if briefing_row else None
    if session is None or session.artifact is None or not any(
        item.source == "news" and item.source_id == "historical-news-fixture"
        for item in session.evidence
    ):
        raise RuntimeError("historical News artifact could not be deserialized by the production reader")
    saved_speech = briefing_store.get_speech_audio(session.id, "production")
    if not saved_speech or not saved_speech.get("chunks") or bytes(saved_speech["chunks"][0]["audio"]) != AUDIO_BYTES:
        raise RuntimeError("saved speech audio could not be read through the production briefing store")
    if not unknown_action or unknown_action[0] != "outcome_unknown" or audit_events < 1 or effects != 1:
        raise RuntimeError("action audit/effect state did not survive import exactly once")
    if not vault or "claims/fixture.md" not in str(vault[0]) or not vault[1]:
        raise RuntimeError("Context vault publication ownership did not survive import")
    env_text = (profile / ".env").read_text(encoding="utf-8")
    if f"APEX_IMPORT_FIXTURE_SECRET={EXPECTED_CREDENTIAL}\n" not in env_text:
        raise RuntimeError("local credential file bytes did not survive import")
    if json.loads((profile / "credentials.json").read_text(encoding="utf-8"))["fixture_token"] != EXPECTED_CREDENTIAL:
        raise RuntimeError("local credential JSON did not survive import")
    local_config = json.loads((profile / "config.local.json").read_text(encoding="utf-8"))
    external_models = profile.parent / "external-models"
    if local_config.get("ollama", {}).get("enabled") is not False:
        raise RuntimeError("rehearsal profile did not disable operator-local Ollama discovery")
    for key, name, expected_bytes in (
        ("executable_path", "llama-server.exe", b"synthetic external model server reference"),
        ("preset_path", "apex-local-models.preset.ini", b"# synthetic fixture preset\n"),
    ):
        expected_reference = str((external_models / name).resolve())
        external_path = external_models / name
        if local_config.get("llama_cpp", {}).get(key) != expected_reference or not external_path.is_file() or external_path.read_bytes() != expected_bytes:
            raise RuntimeError(f"external model reference was not preserved: {key}")
    for relative, expected in (
        ("weights/fastembed/fixture-model.bin", FASTEMBED_FIXTURE_BYTES),
        ("core/weights/kokoro/fixture-model.bin", b"managed kokoro fixture bytes"),
        ("clients/.market_cache.json", b'{"fixture":"market-cache"}\n'),
    ):
        if (profile / relative).read_bytes() != expected:
            raise RuntimeError(f"managed fixture bytes did not survive import: {relative}")
    microsoft_cache_path = _synthetic_microsoft_cache_path(profile)
    from msal_extensions import build_encrypted_persistence

    microsoft_cache_bytes = microsoft_cache_path.read_bytes()
    if EXPECTED_CREDENTIAL.encode() in microsoft_cache_bytes or b"synthetic-only" in microsoft_cache_bytes:
        raise RuntimeError("Microsoft fixture cache unexpectedly contains plaintext")
    if build_encrypted_persistence(str(microsoft_cache_path.resolve())).load() != MICROSOFT_CACHE_TEXT:
        raise RuntimeError("same-user encrypted Microsoft fixture could not be decrypted")
    vault_destination = (profile.parent / "external-context-vault").resolve()
    vault_state = ContextVaultPublicationStateStore(db_path).load(os.path.normcase(str(vault_destination)))
    if "claims/fixture.md" not in vault_state.owned or not vault_state.last_success_at or (vault_destination / "fixture.md").read_text(encoding="utf-8") != "External vault fixture\n":
        raise RuntimeError("Context vault ownership could not be loaded by the production state store")
    return {
        "conversation": True,
        "knowledge": True,
        "report": True,
        "historical_news": True,
        "historical_news_readable": True,
        "speech_audio_bytes": len(AUDIO_BYTES),
        "speech_audio_readable": True,
        "action_status": str(unknown_action[0]),
        "action_events": int(audit_events),
        "action_effects": int(effects),
        "vault_ownership": True,
        "credentials_and_managed_files": True,
        "external_model_references": True,
        "ollama_disabled": True,
        "microsoft_encrypted_cache": "decrypted_with_current_user_dpapi",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument("profile", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("profile", type=Path)
    fingerprint_parser = subparsers.add_parser("fingerprint")
    fingerprint_parser.add_argument("profile", type=Path)
    args = parser.parse_args(argv)
    if args.command == "seed":
        result = seed(args.profile.expanduser().resolve())
    elif args.command == "verify":
        result = verify(args.profile.expanduser().resolve())
    else:
        result = {"fingerprint": managed_fingerprint(args.profile.expanduser().resolve())}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
