"""Versioned local API routes for the Data Audit Experiment foundation."""

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.app import schemas
from backend.app.audit import AuditEngine
from backend.app.reports import audit_csv, audit_json, audit_pdf, safe_report_filename
from backend.app.services import DachikService, SensorLifecycleState

router = APIRouter(prefix="/api/v1")


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.database.session() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def get_service(session: SessionDependency) -> DachikService:
    return DachikService(session)


ServiceDependency = Annotated[DachikService, Depends(get_service)]


@router.get("/devices", response_model=list[schemas.DeviceResponse])
def list_devices(service: ServiceDependency) -> Sequence[object]:
    return service.list_devices()


@router.post("/devices", response_model=schemas.DeviceResponse, status_code=status.HTTP_201_CREATED)
def create_device(payload: schemas.DeviceCreate, service: ServiceDependency) -> object:
    return service.create_device(payload)


@router.get("/bundles", response_model=list[schemas.DataBundleResponse])
def list_bundles(service: ServiceDependency) -> Sequence[object]:
    return service.list_bundles()


@router.post(
    "/bundles", response_model=schemas.DataBundleResponse, status_code=status.HTTP_201_CREATED
)
def create_bundle(payload: schemas.DataBundleCreate, service: ServiceDependency) -> object:
    return service.create_bundle(payload)


@router.get("/experiments", response_model=list[schemas.ExperimentResponse])
def list_experiments(service: ServiceDependency) -> Sequence[object]:
    return service.list_experiments()


@router.post(
    "/experiments", response_model=schemas.ExperimentResponse, status_code=status.HTTP_201_CREATED
)
def create_experiment(payload: schemas.ExperimentCreate, service: ServiceDependency) -> object:
    return service.create_experiment(payload)


@router.get("/experiments/{experiment_id}", response_model=schemas.ExperimentResponse)
def get_experiment(experiment_id: str, service: ServiceDependency) -> object:
    return service.get_experiment(experiment_id)


@router.post("/experiments/{experiment_id}/start", response_model=schemas.ExperimentResponse)
def start_experiment(
    experiment_id: str, service: ServiceDependency, switch_current: bool = False
) -> object:
    return service.start_experiment(experiment_id, switch_current=switch_current)


@router.post(
    "/tracking/current", response_model=schemas.ExperimentResponse
)
def select_current_tracking(
    payload: schemas.CurrentTrackingSelection, service: ServiceDependency
) -> object:
    return service.select_current_experiment(payload.experiment_id)


@router.post("/experiments/{experiment_id}/complete", response_model=schemas.ExperimentResponse)
def complete_experiment(experiment_id: str, service: ServiceDependency) -> object:
    return service.complete_experiment(experiment_id)


@router.post(
    "/experiments/{experiment_id}/isp-snapshots",
    response_model=schemas.ISPBalanceSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_snapshot(
    experiment_id: str,
    payload: schemas.ISPBalanceSnapshotCreate,
    service: ServiceDependency,
) -> object:
    return service.create_snapshot(experiment_id, payload)


@router.get(
    "/experiments/{experiment_id}/isp-snapshots",
    response_model=list[schemas.ISPBalanceSnapshotResponse],
)
def list_snapshots(experiment_id: str, service: ServiceDependency) -> Sequence[object]:
    return service.list_snapshots(experiment_id)


def _sensor_lifecycle(request: Request) -> SensorLifecycleState:
    manager = request.app.state.sensor_service_manager
    status = manager.status()
    return SensorLifecycleState(
        installed=status.installed,
        expected_to_run=status.expected_to_run,
        process_running=status.process_running,
    )


@router.get("/measurement/status", response_model=schemas.MeasurementStatusResponse)
def measurement_status(
    request: Request, service: ServiceDependency
) -> schemas.MeasurementStatusResponse:
    return service.measurement_status(lifecycle=_sensor_lifecycle(request))


@router.get(
    "/usage/current-experiment", response_model=schemas.CurrentExperimentUsageResponse
)
def current_experiment_usage(
    request: Request, service: ServiceDependency, as_of: datetime | None = None
) -> schemas.CurrentExperimentUsageResponse:
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise HTTPException(status_code=422, detail="as_of must include a timezone offset")
    return service.current_experiment_usage(now=as_of, lifecycle=_sensor_lifecycle(request))


def _validated_as_of(as_of: datetime | None) -> datetime | None:
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise HTTPException(status_code=422, detail="as_of must include a timezone offset")
    return as_of


def _audit_state(
    service: DachikService,
    audit_id: str,
    *,
    as_of: datetime | None,
    sensor_status: str = "historical",
) -> schemas.AuditState:
    return AuditEngine(service.repository).build(
        audit_id, as_of=_validated_as_of(as_of), sensor_status=sensor_status
    )


@router.get("/audits", response_model=list[schemas.AuditListItem])
def list_audits(service: ServiceDependency) -> list[schemas.AuditListItem]:
    target = service.repository.get_current_tracking_target()
    result: list[schemas.AuditListItem] = []
    for experiment in service.list_experiments():
        bundle = service.repository.get_bundle(experiment.data_bundle_id)
        if bundle is None:
            continue
        result.append(
            schemas.AuditListItem(
                audit_id=experiment.id,
                provider_name=bundle.provider_name,
                plan_name=bundle.plan_name,
                allowance_bytes=bundle.allowance_bytes,
                audit_start=experiment.started_at,
                bundle_expiry=bundle.billing_cycle_end,
                timezone=bundle.timezone,
                status=cast(
                    Literal["draft", "active", "completed", "cancelled"],
                    experiment.status,
                ),
                is_current=target is not None and target.experiment_id == experiment.id,
            )
        )
    return result


@router.get("/audits/current", response_model=schemas.AuditState)
def current_audit(
    request: Request, service: ServiceDependency, as_of: datetime | None = None
) -> schemas.AuditState:
    experiment = service.current_experiment()
    if experiment is None:
        raise HTTPException(status_code=404, detail="No current data plan")
    sensor = service.measurement_status(lifecycle=_sensor_lifecycle(request)).status
    return _audit_state(service, experiment.id, as_of=as_of, sensor_status=sensor)


@router.get("/audits/{audit_id}", response_model=schemas.AuditState)
def get_audit(
    audit_id: str, service: ServiceDependency, as_of: datetime | None = None
) -> schemas.AuditState:
    return _audit_state(service, audit_id, as_of=as_of)


@router.get("/audits/{audit_id}/export.json")
def export_audit_json(
    audit_id: str, service: ServiceDependency, as_of: datetime | None = None
) -> Response:
    state = _audit_state(service, audit_id, as_of=as_of)
    filename = safe_report_filename(state.provider_name, state.as_of_timestamp, "json")
    return Response(
        audit_json(state),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audits/{audit_id}/export.csv")
def export_audit_csv(
    audit_id: str, service: ServiceDependency, as_of: datetime | None = None
) -> Response:
    state = _audit_state(service, audit_id, as_of=as_of)
    filename = safe_report_filename(state.provider_name, state.as_of_timestamp, "csv")
    return Response(
        audit_csv(state),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audits/{audit_id}/report.pdf")
def export_audit_pdf(
    audit_id: str, service: ServiceDependency, as_of: datetime | None = None
) -> Response:
    state = _audit_state(service, audit_id, as_of=as_of)
    filename = safe_report_filename(state.provider_name, state.as_of_timestamp, "pdf")
    return Response(
        audit_pdf(state),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
