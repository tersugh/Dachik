"""Versioned local API routes for the Data Audit Experiment foundation."""

from collections.abc import Iterator, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from backend.app import schemas
from backend.app.services import DachikService

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
def start_experiment(experiment_id: str, service: ServiceDependency) -> object:
    return service.start_experiment(experiment_id)


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
