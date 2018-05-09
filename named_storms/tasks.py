from __future__ import absolute_import, unicode_literals
from datetime import datetime
from django.core.files import File
from django.core.files.storage import default_storage
import os
import tarfile
import requests
from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from cwwed.celery import app
from named_storms.data.processors import ProcessorData
from named_storms.models import NamedStorm, CoveredDataProvider, CoveredData, NamedStormCoveredDataLog, NSEM
from named_storms.utils import (
    processor_class, named_storm_covered_data_archive_path, copy_path_to_default_storage, named_storm_nsem_version_path,
    create_directory)

RETRY_ARGS = dict(
    autoretry_for=(Exception,),
    default_retry_delay=5,
    max_retries=10,
)


@app.task(**RETRY_ARGS)
def fetch_url_task(url, verify=True, write_to_path=None):
    """
    :param url: URL to fetch
    :param verify: whether to verify ssl
    :param write_to_path: path to store the output vs returning it
    """
    stream = write_to_path is not None
    response = requests.get(url, verify=verify, timeout=10, stream=stream)
    response.raise_for_status()

    # save content
    if write_to_path is not None:
        with open(write_to_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)
        return None

    # return content
    return response.content.decode()  # must return bytes for serialization


@app.task(**RETRY_ARGS)
def process_dataset_task(data: list):
    """
    Run the dataset processor
    """
    processor_data = ProcessorData(*data)
    named_storm = get_object_or_404(NamedStorm, pk=processor_data.named_storm_id)
    provider = get_object_or_404(CoveredDataProvider, pk=processor_data.provider_id)
    processor_cls = processor_class(provider)
    processor = processor_cls(
        named_storm=named_storm,
        provider=provider,
        url=processor_data.url,
        label=processor_data.label,
        group=processor_data.group,
    )
    processor.fetch()
    return processor.to_dict()


@app.task(**RETRY_ARGS)
def archive_named_storm_covered_data(named_storm_id, covered_data_id, log_id):
    """
    :param named_storm_id: id for a NamedStorm record
    :param covered_data_id: id for a CoveredData record
    :param log_id: id for a NamedStormCoveredDataLog
    """
    named_storm = get_object_or_404(NamedStorm, pk=named_storm_id)
    covered_data = get_object_or_404(CoveredData, pk=covered_data_id)
    log = get_object_or_404(NamedStormCoveredDataLog, pk=log_id)

    archive_path = named_storm_covered_data_archive_path(named_storm, covered_data)
    tar_path = '{}.{}'.format(
        os.path.join(os.path.dirname(archive_path), os.path.basename(archive_path)),  # guarantees no trailing slash
        settings.CWWED_ARCHIVE_EXTENSION,
    )

    # create tar in local storage
    tar = tarfile.open(tar_path, mode=settings.CWWED_NSEM_ARCHIVE_WRITE_MODE)
    tar.add(archive_path, arcname=os.path.basename(archive_path))
    tar.close()

    storage_path = os.path.join(
        settings.CWWED_COVERED_ARCHIVE_DIR_NAME,
        named_storm.name,
        os.path.basename(tar_path),
    )

    # copy tar to default storage
    snapshot_path = copy_path_to_default_storage(tar_path, storage_path)

    # remove local tar
    os.remove(tar_path)

    # update the log with the saved snapshot
    log.snapshot = snapshot_path
    log.save()

    return log.snapshot


@app.task(**RETRY_ARGS)
def archive_nsem_covered_data(nsem_id):
    """
    Creates a single archive from all the covered data archives to pass off to the external NSEM
    """

    # retrieve all the successful covered data by querying the logs
    # exclude any logs where the snapshot archive hasn't been created yet
    # sort by date descending and retrieve unique results
    nsem = get_object_or_404(NSEM, pk=int(nsem_id))
    logs = nsem.named_storm.namedstormcovereddatalog_set.filter(success=True).exclude(snapshot='').order_by('-date')
    if not logs.exists():
        return None
    logs_to_archive = []
    for log in logs:
        if log.covered_data.name not in [l.covered_data.name for l in logs_to_archive]:
            logs_to_archive.append(log)

    storage_path = os.path.join(
        settings.CWWED_NSEM_DIR_NAME,
        nsem.named_storm.name,
        'v{}'.format(nsem.id),
        settings.CWWED_COVERED_DATA_DIR_NAME,
    )

    for log in logs:
        src_path = log.snapshot
        dest_path = os.path.join(storage_path, os.path.basename(src_path))
        # copy snapshot to versioned nsem location in default storage
        default_storage.copy_within_storage(src_path, dest_path)

    nsem.covered_data_snapshot = storage_path
    nsem.save()

    return default_storage.url(storage_path)


@app.task(**RETRY_ARGS)
def extract_nsem_model_output(nsem_id):
    """
    Downloads the model product output from object storage and puts it in file storage
    """

    nsem = get_object_or_404(NSEM, pk=int(nsem_id))

    # verify this instance needs it's model output to be extracted (don't raise an exception, though)
    if nsem.model_output_snapshot_extracted:
        return None
    # verify the uploaded output exists in storage
    elif not default_storage.exists(nsem.model_output_snapshot):
        raise Http404("{} doesn't exist in storage".format(nsem.model_output_snapshot))

    storage_path = os.path.join(
        settings.CWWED_NSEM_DIR_NAME,
        nsem.named_storm.name,
        'v{}'.format(nsem.id),
        settings.CWWED_NSEM_PSA_DIR_NAME,
        os.path.basename(nsem.model_output_snapshot),
    )

    # copy from "upload" directory to the versioned path
    default_storage.copy_within_storage(nsem.model_output_snapshot, storage_path)

    # delete the old, uploaded copy
    default_storage.delete(nsem.model_output_snapshot)

    with default_storage.open(storage_path, 'rb') as sd:
        file_system_path = os.path.join(
            named_storm_nsem_version_path(nsem),
            os.path.basename(nsem.model_output_snapshot),
        )

        # create the versioned path
        create_directory(os.path.dirname(file_system_path))

        # write to file system path
        with File(open(file_system_path, 'wb')) as dd:
            for chunk in sd.chunks():
                dd.write(chunk)

        # extract the tgz to file storage
        tar = tarfile.open(file_system_path, settings.CWWED_NSEM_ARCHIVE_READ_MODE)
        tar.extractall(os.path.dirname(file_system_path))
        tar.close()

        # remove the tgz now that we've extracted everything
        os.remove(file_system_path)

    # update output path to the copied path, flag success and set the date returned
    nsem.model_output_snapshot = storage_path
    nsem.model_output_snapshot_extracted = True
    nsem.date_returned = datetime.utcnow()
    nsem.save()

    return default_storage.url(storage_path)
