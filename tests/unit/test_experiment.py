"""Tests for the AQCS Experiment Tracking Layer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from aqcs.experiments.fingerprint import (
    fingerprint_dataset,
    fingerprint_file,
    get_git_commit_hash,
)
from aqcs.experiments.models import ExperimentRecord, ExperimentStatus
from aqcs.experiments.storage import (
    list_experiments,
    load_experiment_json,
    save_experiment_json,
)
from aqcs.experiments.tracker import ExperimentTracker
from aqcs.utils.event_bus import EventBus
from aqcs.utils.events import (
    EventCategory,
    ExperimentCompletedEvent,
    ExperimentFailedEvent,
    ExperimentStartedEvent,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _make_record(**kwargs) -> ExperimentRecord:
    defaults = dict(
        experiment_name="test_experiment",
        timestamp_started_utc=_utc_now(),
    )
    defaults.update(kwargs)
    return ExperimentRecord(**defaults)


# ── ExperimentStatus ──────────────────────────────────────────────────────────


class TestExperimentStatus:
    def test_all_required_statuses_exist(self) -> None:
        expected = {"created", "running", "completed", "failed", "cancelled"}
        actual = {s.value for s in ExperimentStatus}
        assert expected == actual

    def test_status_is_string_enum(self) -> None:
        assert isinstance(ExperimentStatus.RUNNING, str)
        assert ExperimentStatus.COMPLETED == "completed"


# ── ExperimentRecord ──────────────────────────────────────────────────────────


class TestExperimentRecord:
    def test_creation_with_required_fields(self) -> None:
        rec = _make_record()
        assert isinstance(rec.experiment_id, UUID)
        assert rec.experiment_name == "test_experiment"
        assert rec.status == ExperimentStatus.CREATED

    def test_default_status_is_created(self) -> None:
        rec = _make_record()
        assert rec.status == ExperimentStatus.CREATED

    def test_default_type_is_research(self) -> None:
        rec = _make_record()
        assert rec.experiment_type == "research"

    def test_python_version_captured(self) -> None:
        rec = _make_record()
        assert rec.python_version  # non-empty

    def test_platform_captured(self) -> None:
        rec = _make_record()
        assert rec.platform  # non-empty

    def test_metrics_default_empty(self) -> None:
        rec = _make_record()
        assert rec.metrics == {}

    def test_artifacts_default_empty(self) -> None:
        rec = _make_record()
        assert rec.artifacts == []

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(Exception, match="UTC-aware"):
            _make_record(timestamp_started_utc=datetime(2024, 1, 1))

    def test_non_utc_timestamp_rejected(self) -> None:
        from zoneinfo import ZoneInfo

        ny = datetime(2024, 1, 1, tzinfo=ZoneInfo("America/New_York"))
        with pytest.raises(Exception, match="UTC"):
            _make_record(timestamp_started_utc=ny)

    def test_utc_timestamp_accepted(self) -> None:
        rec = _make_record(timestamp_started_utc=datetime(2024, 6, 1, tzinfo=UTC))
        assert rec.timestamp_started_utc.tzinfo == UTC

    def test_json_serializable(self) -> None:
        rec = _make_record(parameters={"lr": 0.01}, tags=["baseline"])
        data = rec.model_dump(mode="json")
        dumped = json.dumps(data)  # must not raise
        assert "test_experiment" in dumped

    def test_all_required_fields_present(self) -> None:
        rec = _make_record()
        required = [
            "experiment_id",
            "experiment_name",
            "experiment_type",
            "status",
            "timestamp_started_utc",
            "timestamp_completed_utc",
            "git_commit_hash",
            "python_version",
            "platform",
            "config_path",
            "dataset_fingerprint",
            "dataset_paths",
            "parameters",
            "metrics",
            "tags",
            "notes",
            "artifacts",
            "duration_seconds",
        ]
        data = rec.model_dump()
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_record_is_mutable(self) -> None:
        rec = _make_record()
        rec.status = ExperimentStatus.RUNNING
        assert rec.status == ExperimentStatus.RUNNING


# ── ExperimentTracker ─────────────────────────────────────────────────────────


class TestExperimentTracker:
    def test_create_experiment_returns_running_record(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("btc_test")
        assert rec.status == ExperimentStatus.RUNNING
        assert rec.experiment_name == "btc_test"

    def test_create_experiment_saves_json_to_disk(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("disk_test")
        files = list(tmp_path.rglob("experiment_*.json"))
        assert len(files) == 1
        assert str(rec.experiment_id) in files[0].name

    def test_create_experiment_captures_git_hash(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("git_test", capture_git=True)
        assert isinstance(rec.git_commit_hash, str)  # may be "" if not in git

    def test_create_experiment_no_git_returns_empty(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("nogit_test", capture_git=False)
        assert rec.git_commit_hash == ""

    def test_complete_experiment_transitions_status(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("complete_test")
        completed = tracker.complete_experiment(rec.experiment_id)
        assert completed.status == ExperimentStatus.COMPLETED

    def test_complete_experiment_sets_completed_timestamp(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("ts_test")
        completed = tracker.complete_experiment(rec.experiment_id)
        assert completed.timestamp_completed_utc is not None
        assert completed.timestamp_completed_utc.tzinfo == UTC

    def test_complete_experiment_computes_duration(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("dur_test")
        completed = tracker.complete_experiment(rec.experiment_id)
        assert completed.duration_seconds is not None
        assert completed.duration_seconds >= 0.0

    def test_complete_experiment_saves_metrics(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("metrics_test")
        completed = tracker.complete_experiment(
            rec.experiment_id, metrics={"sharpe": 1.4, "max_dd": -0.12}
        )
        assert completed.metrics["sharpe"] == 1.4
        assert completed.metrics["max_dd"] == -0.12

    def test_complete_experiment_saves_artifacts(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("artifacts_test")
        completed = tracker.complete_experiment(
            rec.experiment_id, artifacts=["results/equity_curve.parquet"]
        )
        assert "results/equity_curve.parquet" in completed.artifacts

    def test_fail_experiment_transitions_status(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("fail_test")
        failed = tracker.fail_experiment(rec.experiment_id, reason="data gap detected")
        assert failed.status == ExperimentStatus.FAILED

    def test_fail_experiment_saves_reason_in_notes(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("reason_test")
        failed = tracker.fail_experiment(rec.experiment_id, reason="data gap at 2024-01-15")
        assert "data gap at 2024-01-15" in failed.notes

    def test_fail_experiment_computes_duration(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("fail_dur_test")
        failed = tracker.fail_experiment(rec.experiment_id)
        assert failed.duration_seconds is not None
        assert failed.duration_seconds >= 0.0

    def test_cannot_complete_already_completed(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("double_complete")
        tracker.complete_experiment(rec.experiment_id)
        with pytest.raises(ValueError, match="Cannot transition"):
            tracker.complete_experiment(rec.experiment_id)

    def test_cannot_fail_already_failed(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("double_fail")
        tracker.fail_experiment(rec.experiment_id)
        with pytest.raises(ValueError, match="Cannot transition"):
            tracker.fail_experiment(rec.experiment_id)

    def test_cannot_complete_already_failed(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("fail_then_complete")
        tracker.fail_experiment(rec.experiment_id)
        with pytest.raises(ValueError):
            tracker.complete_experiment(rec.experiment_id)

    def test_unknown_experiment_id_raises_key_error(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        with pytest.raises(KeyError):
            tracker.complete_experiment(uuid4())

    def test_save_experiment_writes_json(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = _make_record()
        path = tracker.save_experiment(rec)
        assert path.exists()
        assert path.suffix == ".json"

    def test_get_experiment_returns_record(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("get_test")
        retrieved = tracker.get_experiment(rec.experiment_id)
        assert retrieved is rec

    def test_get_unknown_experiment_returns_none(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        assert tracker.get_experiment(uuid4()) is None

    def test_parameters_stored(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        params = {"lookback": 90, "threshold": 0.02}
        rec = tracker.create_experiment("params_test", parameters=params)
        assert rec.parameters == params

    def test_tags_stored(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("tag_test", tags=["baseline", "btc"])
        assert "baseline" in rec.tags


# ── EventBus integration ──────────────────────────────────────────────────────


class TestEventBusIntegration:
    def test_started_event_emitted_on_create(self, tmp_path: Path) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.EXPERIMENT)
        tracker = ExperimentTracker(tmp_path, bus=bus)
        tracker.create_experiment("bus_test")
        assert len(events) == 1
        assert isinstance(events[0], ExperimentStartedEvent)

    def test_completed_event_emitted(self, tmp_path: Path) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.EXPERIMENT)
        tracker = ExperimentTracker(tmp_path, bus=bus)
        rec = tracker.create_experiment("complete_bus")
        tracker.complete_experiment(rec.experiment_id, metrics={"sharpe": 1.2})
        assert any(isinstance(e, ExperimentCompletedEvent) for e in events)

    def test_failed_event_emitted(self, tmp_path: Path) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.EXPERIMENT)
        tracker = ExperimentTracker(tmp_path, bus=bus)
        rec = tracker.create_experiment("fail_bus")
        tracker.fail_experiment(rec.experiment_id, reason="test failure")
        assert any(isinstance(e, ExperimentFailedEvent) for e in events)

    def test_no_bus_does_not_raise(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path, bus=None)
        rec = tracker.create_experiment("no_bus")
        tracker.complete_experiment(rec.experiment_id)  # must not raise


# ── Git hash capture ──────────────────────────────────────────────────────────


class TestGitHashCapture:
    def test_returns_string_always(self) -> None:
        result = get_git_commit_hash()
        assert isinstance(result, str)

    def test_returns_empty_when_git_unavailable(self) -> None:
        with patch("aqcs.experiments.fingerprint.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")
            result = get_git_commit_hash()
        assert result == ""

    def test_returns_empty_on_non_zero_exit(self) -> None:
        with patch("aqcs.experiments.fingerprint.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stdout = ""
            result = get_git_commit_hash()
        assert result == ""

    def test_returns_40_char_hash_when_present(self) -> None:
        with patch("aqcs.experiments.fingerprint.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "abc1234def5678abc1234def5678abc1234def56\n"
            result = get_git_commit_hash()
        assert len(result) == 40


# ── Dataset fingerprinting ────────────────────────────────────────────────────


class TestDatasetFingerprinting:
    def test_fingerprint_file_returns_hex_string(self, tmp_path: Path) -> None:
        f = tmp_path / "data.parquet"
        f.write_bytes(b"fake parquet data")
        fp = fingerprint_file(f)
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex

    def test_fingerprint_nonexistent_file_returns_empty(self) -> None:
        fp = fingerprint_file(Path("/nonexistent/file.parquet"))
        assert fp == ""

    def test_fingerprint_is_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "data.parquet"
        f.write_bytes(b"deterministic content")
        assert fingerprint_file(f) == fingerprint_file(f)

    def test_fingerprint_dataset_empty_list_returns_empty(self) -> None:
        assert fingerprint_dataset([]) == ""

    def test_fingerprint_dataset_with_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.parquet"
        f2 = tmp_path / "b.parquet"
        f1.write_bytes(b"file a")
        f2.write_bytes(b"file b")
        fp = fingerprint_dataset([f1, f2])
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_fingerprint_dataset_is_deterministic(self, tmp_path: Path) -> None:
        f1 = tmp_path / "x.parquet"
        f1.write_bytes(b"content x")
        fp1 = fingerprint_dataset([f1])
        fp2 = fingerprint_dataset([f1])
        assert fp1 == fp2

    def test_fingerprint_dataset_order_independent(self, tmp_path: Path) -> None:
        f1 = tmp_path / "p.parquet"
        f2 = tmp_path / "q.parquet"
        f1.write_bytes(b"file p")
        f2.write_bytes(b"file q")
        assert fingerprint_dataset([f1, f2]) == fingerprint_dataset([f2, f1])

    def test_fingerprint_dataset_different_files_different_result(self, tmp_path: Path) -> None:
        f1 = tmp_path / "m.parquet"
        f2 = tmp_path / "n.parquet"
        f1.write_bytes(b"content m")
        f2.write_bytes(b"content n - different")
        assert fingerprint_dataset([f1]) != fingerprint_dataset([f2])


# ── Local storage ─────────────────────────────────────────────────────────────


class TestLocalStorage:
    def test_save_creates_json_file(self, tmp_path: Path) -> None:
        rec = _make_record()
        path = save_experiment_json(rec, tmp_path)
        assert path.exists()
        assert path.suffix == ".json"

    def test_save_creates_date_partitioned_directory(self, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        rec = _make_record(timestamp_started_utc=now)
        path = save_experiment_json(rec, tmp_path)
        date_str = now.strftime("%Y-%m-%d")
        assert date_str in str(path)

    def test_no_tmp_file_after_save(self, tmp_path: Path) -> None:
        rec = _make_record()
        save_experiment_json(rec, tmp_path)
        tmp_files = list(tmp_path.rglob("*.tmp.json"))
        assert tmp_files == []

    def test_load_roundtrip(self, tmp_path: Path) -> None:
        rec = _make_record(experiment_name="roundtrip_test", tags=["a", "b"])
        path = save_experiment_json(rec, tmp_path)
        loaded = load_experiment_json(path)
        assert loaded.experiment_id == rec.experiment_id
        assert loaded.experiment_name == rec.experiment_name
        assert loaded.tags == rec.tags

    def test_saved_json_is_valid_utf8(self, tmp_path: Path) -> None:
        rec = _make_record(notes="Test with unicode: árbol 🌳")
        path = save_experiment_json(rec, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "árbol" in content

    def test_list_experiments_returns_all_files(self, tmp_path: Path) -> None:
        for name in ["exp_a", "exp_b", "exp_c"]:
            rec = _make_record(experiment_name=name)
            save_experiment_json(rec, tmp_path)
        files = list_experiments(tmp_path)
        assert len(files) == 3

    def test_list_experiments_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        assert list_experiments(tmp_path) == []

    def test_list_experiments_nonexistent_dir_returns_empty(self) -> None:
        assert list_experiments(Path("/nonexistent/dir")) == []

    def test_persistence_after_complete(self, tmp_path: Path) -> None:
        tracker = ExperimentTracker(tmp_path)
        rec = tracker.create_experiment("persist_test")
        tracker.complete_experiment(rec.experiment_id, metrics={"sharpe": 1.5})
        files = list_experiments(tmp_path)
        assert len(files) == 1
        loaded = load_experiment_json(files[0])
        assert loaded.status == ExperimentStatus.COMPLETED
        assert loaded.metrics["sharpe"] == 1.5

    def test_saved_json_has_sorted_keys(self, tmp_path: Path) -> None:
        rec = _make_record(parameters={"z_param": 1, "a_param": 2})
        path = save_experiment_json(rec, tmp_path)
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        top_keys = list(data.keys())
        assert top_keys == sorted(top_keys), "Top-level JSON keys must be sorted"

    def test_repeated_saves_produce_identical_json(self, tmp_path: Path) -> None:
        rec = _make_record(experiment_name="deterministic", parameters={"b": 2, "a": 1})
        path1 = save_experiment_json(rec, tmp_path)
        content1 = path1.read_text(encoding="utf-8")
        path2 = save_experiment_json(rec, tmp_path)
        content2 = path2.read_text(encoding="utf-8")
        assert content1 == content2


# ── JSON serializability enforcement ─────────────────────────────────────────


class TestJSONSerializability:
    def test_dict_parameters_accepted(self) -> None:
        rec = _make_record(parameters={"lookback": 90, "threshold": 0.02, "name": "v1"})
        assert rec.parameters["lookback"] == 90

    def test_nested_dict_parameters_accepted(self) -> None:
        rec = _make_record(parameters={"nested": {"key": "value"}, "count": 3})
        assert rec.parameters["nested"]["key"] == "value"

    def test_non_serializable_parameters_rejected(self) -> None:
        with pytest.raises(Exception, match="JSON-serializable"):
            _make_record(parameters={"obj": object()})

    def test_lambda_in_parameters_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_record(parameters={"fn": lambda x: x})

    def test_float_metric_accepted(self) -> None:
        rec = _make_record()
        rec.metrics["sharpe"] = 1.4
        assert rec.metrics["sharpe"] == 1.4

    def test_int_metric_accepted(self) -> None:
        rec = _make_record(metrics={"n_trades": 42})
        assert rec.metrics["n_trades"] == 42

    def test_bool_metric_accepted(self) -> None:
        rec = _make_record(metrics={"converged": True})
        assert rec.metrics["converged"] is True

    def test_str_metric_accepted(self) -> None:
        rec = _make_record(metrics={"best_symbol": "BTC/USDT"})
        assert rec.metrics["best_symbol"] == "BTC/USDT"

    def test_none_metric_accepted(self) -> None:
        rec = _make_record(metrics={"optional_stat": None})
        assert rec.metrics["optional_stat"] is None

    def test_list_metric_rejected(self) -> None:
        with pytest.raises(Exception, match="JSON scalar"):
            _make_record(metrics={"equity_curve": [1.0, 1.1, 1.2]})

    def test_dict_metric_rejected(self) -> None:
        with pytest.raises(Exception, match="JSON scalar"):
            _make_record(metrics={"nested": {"a": 1}})

    def test_object_metric_rejected(self) -> None:
        with pytest.raises(Exception, match="JSON scalar"):
            _make_record(metrics={"obj": object()})


# ── Portable fingerprinting with dataset_root ─────────────────────────────────


class TestPortableFingerprinting:
    def test_fingerprint_with_dataset_root(self, tmp_path: Path) -> None:
        root = tmp_path / "data"
        root.mkdir()
        f = root / "BTC_USDT_1d.parquet"
        f.write_bytes(b"parquet data")
        fp = fingerprint_file(f, dataset_root=root)
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_fingerprint_relative_path_differs_from_absolute(self, tmp_path: Path) -> None:
        root = tmp_path / "data"
        root.mkdir()
        f = root / "BTC_USDT_1d.parquet"
        f.write_bytes(b"parquet data")
        fp_abs = fingerprint_file(f)
        fp_rel = fingerprint_file(f, dataset_root=root)
        assert fp_abs != fp_rel  # different path strings → different fingerprints

    def test_fingerprint_dataset_portable_is_deterministic(self, tmp_path: Path) -> None:
        root = tmp_path / "data"
        root.mkdir()
        f1 = root / "a.parquet"
        f2 = root / "b.parquet"
        f1.write_bytes(b"file a")
        f2.write_bytes(b"file b")
        fp1 = fingerprint_dataset([f1, f2], dataset_root=root)
        fp2 = fingerprint_dataset([f1, f2], dataset_root=root)
        assert fp1 == fp2

    def test_fingerprint_dataset_portable_order_independent(self, tmp_path: Path) -> None:
        root = tmp_path / "data"
        root.mkdir()
        f1 = root / "x.parquet"
        f2 = root / "y.parquet"
        f1.write_bytes(b"file x")
        f2.write_bytes(b"file y")
        assert fingerprint_dataset([f1, f2], dataset_root=root) == fingerprint_dataset(
            [f2, f1], dataset_root=root
        )

    def test_missing_file_with_dataset_root_returns_empty(self) -> None:
        root = Path("/some/root")
        fp = fingerprint_file(Path("/some/root/missing.parquet"), dataset_root=root)
        assert fp == ""


# ── repo_root in git hash capture ─────────────────────────────────────────────


class TestGitHashWithRepoRoot:
    def test_repo_root_passed_as_cwd(self, tmp_path: Path) -> None:
        with patch("aqcs.experiments.fingerprint.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "abc1234\n"
            get_git_commit_hash(repo_root=tmp_path)
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get("cwd") == tmp_path

    def test_no_repo_root_does_not_pass_cwd(self) -> None:
        with patch("aqcs.experiments.fingerprint.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "abc1234\n"
            get_git_commit_hash()
            call_kwargs = mock_run.call_args[1]
            assert "cwd" not in call_kwargs

    def test_repo_root_graceful_fallback(self, tmp_path: Path) -> None:
        with patch("aqcs.experiments.fingerprint.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")
            result = get_git_commit_hash(repo_root=tmp_path)
        assert result == ""


# ── Generic ExperimentStartedEvent ───────────────────────────────────────────


class TestGenericExperimentEvent:
    def test_started_event_has_no_trading_fields(self, tmp_path: Path) -> None:
        from aqcs.utils.events import ExperimentStartedEvent

        ev = ExperimentStartedEvent(
            component="aqcs.experiments.tracker",
            experiment_name="test",
            experiment_type="research",
            git_commit="abc123",
            dataset_fingerprint="deadbeef",
            dataset_paths=["data/raw/BTC_USDT_1d.parquet"],
        )
        assert not hasattr(ev, "symbols")
        assert not hasattr(ev, "timeframe")
        assert not hasattr(ev, "start_date")
        assert not hasattr(ev, "end_date")
        assert ev.experiment_type == "research"
        assert ev.dataset_fingerprint == "deadbeef"

    def test_started_event_emitted_with_generic_fields(self, tmp_path: Path) -> None:
        from aqcs.utils.events import ExperimentStartedEvent

        bus = EventBus()
        events: list = []
        bus.subscribe(events.append)
        tracker = ExperimentTracker(tmp_path, bus=bus)
        tracker.create_experiment(
            "generic_test",
            experiment_type="data_quality",
            dataset_paths=["data/raw/BTC_USDT_1d.parquet"],
        )
        started = next(e for e in events if isinstance(e, ExperimentStartedEvent))
        assert started.experiment_type == "data_quality"
        assert "data/raw/BTC_USDT_1d.parquet" in started.dataset_paths
