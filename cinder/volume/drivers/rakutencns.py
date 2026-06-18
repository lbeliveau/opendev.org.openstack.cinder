#
# Copyright (c) 2019-2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from enum import IntEnum
import errno
import http.client
import json
import os
import requests
import socket
import ssl
import subprocess
import time

from oslo_config import cfg
from oslo_log import log as logging

from cinder import exception
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)

KUBERNETES_API_SERVER = "https://kubernetes.default.svc"
KUBERNETES_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
KUBERNETES_CA_CERT_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

ROBIN_NS = 'robinio'
ROBIN_SVC = 'robin-master-ext'
ROBIN_SVC_PORT = 29442

RETRIES_HTTPS_CONN = 5
TIMEOUT_HTTPS_CONN = 5
TIMEOUT_JOB = 90
TIMEOUT_VOLUME = 90


class RakutenCNSException(exception.VolumeBackendAPIException):
        def __init__(self, message):
            super().__init__(message)


class RakutenCNSService:
    """
    Helper class to abstract the Rakuten Kubernetes resources.
    """

    def get(self) -> tuple[str, int]:
        """
        Retrieve the CNS service IP and port from the Kubernetes API.

        Queries the Kubernetes API for the Robin master service endpoint
        in the robinio namespace and returns the cluster IP and port.
        """
        # TODO: Use kubernetes client library instead of raw HTTP calls (need to install packages in the image)
        with open(KUBERNETES_TOKEN_PATH, "r") as f:
            token = f.read().strip()

        url = f"{KUBERNETES_API_SERVER}/api/v1/namespaces/{ROBIN_NS}/services/{ROBIN_SVC}"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        response = requests.get(url, headers=headers, verify=KUBERNETES_CA_CERT_PATH)
        if response.status_code == 200:
            data = response.json()
            return data['spec']['clusterIP'], ROBIN_SVC_PORT
        else:
            raise RakutenCNSException(f"Failed to get service IP: {response.status_code} {response.text}")


class RakutenCNSVolumeState(IntEnum):
    """
    Enum representing the states of a Rakuten CNS volume.
    """

    REGISTERING = 1
    READY = 2
    FAULTED = 9
    REGISTERED = 12
    MOUNTING = 13
    MOUNTED = 14
    DELETE_FAILED = 17
    UNMOUNT_FAILED = 18
    DEGRADED = 19
    EVACUATING = 21
    EVACUATED = 22
    DETACHED = 27
    ATTACH_FAILED = 28
    DETACH_FAILED = 29
    UNFAULTING = 32
    REMOUNTING = 34
    REMOUNT_FAILED = 35
    INITIALIZING = 36
    ACCESS_FAILED = 38

    @property
    def description(self):
        descriptions = {
            RakutenCNSVolumeState.REGISTERING: "REGISTERING",
            RakutenCNSVolumeState.READY: "READY",
            RakutenCNSVolumeState.FAULTED: "FAULTED",
            RakutenCNSVolumeState.REGISTERED: "REGISTERED",
            RakutenCNSVolumeState.MOUNTING: "MOUNTING",
            RakutenCNSVolumeState.MOUNTED: "MOUNTED",
            RakutenCNSVolumeState.DELETE_FAILED: "DELETE_FAILED",
            RakutenCNSVolumeState.UNMOUNT_FAILED: "UNMOUNT_FAILED",
            RakutenCNSVolumeState.DEGRADED: "DEGRADED",
            RakutenCNSVolumeState.EVACUATING: "EVACUATING",
            RakutenCNSVolumeState.EVACUATED: "EVACUATED",
            RakutenCNSVolumeState.DETACHED: "DETACHED",
            RakutenCNSVolumeState.ATTACH_FAILED: "ATTACH_FAILED",
            RakutenCNSVolumeState.DETACH_FAILED: "DETACH_FAILED",
            RakutenCNSVolumeState.UNFAULTING: "UNFAULTING",
            RakutenCNSVolumeState.REMOUNTING: "REMOUNTING",
            RakutenCNSVolumeState.REMOUNT_FAILED: "REMOUNT_FAILED",
            RakutenCNSVolumeState.INITIALIZING: "INITIALIZING",
            RakutenCNSVolumeState.ACCESS_FAILED: "ACCESS_FAILED",
        }
        return descriptions.get(self, "Unknown")


class RakutenCNSVolumeStatus(IntEnum):
    """
    Enum representing the status of a Rakuten CNS volume.
    """

    ONLINE = 1
    OFFLINE = 2
    DEGRADED = 3
    FAULTED = 4
    ACCESS_FAILED = 5
    UNKNOWN = 7

    @property
    def description(self):
        descriptions = {
            RakutenCNSVolumeStatus.ONLINE: "ONLINE",
            RakutenCNSVolumeStatus.OFFLINE: "OFFLINE",
            RakutenCNSVolumeStatus.DEGRADED: "DEGRADED",
            RakutenCNSVolumeStatus.FAULTED: "FAULTED",
            RakutenCNSVolumeStatus.ACCESS_FAILED: "ACCESS_FAILED",
            RakutenCNSVolumeStatus.UNKNOWN: "UNKNOWN",
        }
        return descriptions.get(self, "Unknown")


class RakutenCNSJobState(IntEnum):
    """
    Enum representing the status of a Rakuten CNS job.
    """
    INIT = 1
    VALIDATED = 2
    PREPARED = 3
    WAITING = 4
    DONE = 5
    UNDONE = 6
    NOTIFIED = 7
    AGENT_WAIT = 8
    FINALIZED = 9
    COMPLETED = 10
    ARCHIVED = 11
    PURGED = 12
    PROCESSED = 13

    @property
    def description(self):
        descriptions = {
            RakutenCNSJobState.INIT: "Initialized",
            RakutenCNSJobState.VALIDATED: "Validated",
            RakutenCNSJobState.PREPARED: "Prepared",
            RakutenCNSJobState.WAITING: "Waiting",
            RakutenCNSJobState.DONE: "Done",
            RakutenCNSJobState.UNDONE: "Undone",
            RakutenCNSJobState.NOTIFIED: "Notified",
            RakutenCNSJobState.AGENT_WAIT: "Agent Wait",
            RakutenCNSJobState.FINALIZED: "Finalized",
            RakutenCNSJobState.COMPLETED: "Completed",
            RakutenCNSJobState.ARCHIVED: "Archived",
            RakutenCNSJobState.PURGED: "Purged",
            RakutenCNSJobState.PROCESSED: "Processed",
        }
        return descriptions.get(self, "Unknown")


class RakutenCNSAPI:
    """
    Helper class to interact with the Rakuten CNS REST API.
    """

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.token = None

        self._cns_service_ip, self._cns_server_port = RakutenCNSService().get()
        self.url = f"{self._cns_service_ip}:{self._cns_server_port}"
        LOG.info("url: %s", self.url)

        # Try to get a token to verify connectivity and credentials, an exception will be raised if it fails
        self.token = self._get_token(self.username, self.password)
        LOG.info("token: %s", self.token)

    def _get_token(self, username: str, password: str, verify_ssl: bool = False) -> str:
        """
        Authenticate against the Rakuten CNS REST API and return an auth token.
        """
        url = f"https://{self.url}/api/v6/robin_server/login"
        headers = {"Content-Type": "application/json"}
        payload = {"username": username, "password": password}

        response = requests.post(url, json=payload, headers=headers, verify=verify_ssl)
        response.raise_for_status()

        return response.json()["token"]

    def _api_call(self, method: str, path: str, body: dict = None, debug: bool = False):
        """
        Make an authenticated API call to the Rakuten CNS REST API with retry logic.
        """
        LOG.info("RakutenCNSAPI._api_call(): method=%s, path=%s, body=%s", method, path, json.dumps(body) if body else None)

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        retry = 0
        last_error = None
        while True:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}"
            }

            connection = http.client.HTTPSConnection(self.url, timeout=TIMEOUT_HTTPS_CONN, context=ctx)
            try:
                connection.request(method, path, json.dumps(body) if body else None, headers)
                response = connection.getresponse()
                LOG.info("HTTP response status: %s %s", response.status, response.reason)
                data = response.read()
                jres = json.loads(data)
                if debug:
                    LOG.info("response: %s", json.dumps(jres, indent=4))

                if response.status in (http.client.OK, http.client.ACCEPTED):
                    return jres
                elif response.status == http.client.UNAUTHORIZED:
                    # Try to refresh the token
                    self.token = self._get_token(self.username, self.password)
                else:
                    last_error = RakutenCNSException(f"REST API call failed: {response.status}")
            except (
                    ConnectionRefusedError,
                    socket.timeout,
                    socket.gaierror,
                    TimeoutError,
                    OSError) as e:
                # Try to refresh the connection destination
                LOG.exception("Connection error: %s", e)
                self._cns_service_ip, self._cns_server_port = RakutenCNSService().get()
                self.url = f"{self._cns_service_ip}:{self._cns_server_port}"
            except Exception as e:
                LOG.exception("Error: %s", e)
                last_error = e
            finally:
                if connection:
                    connection.close()

            if retry >= RETRIES_HTTPS_CONN:
                raise last_error
            
            time.sleep(2**retry)
            retry += 1

    def _get_job(self, job_id: str, debug: bool = False) -> dict:
        """
        Get the details of a specific job by its ID.
        """
        return self._api_call('GET', f'/api/v3/robin_server/jobs/{job_id}', debug)

    def _wait_for_job_completion(self, jobid: str, debug: bool = False) -> None:
        """
        Poll a job until it reaches COMPLETED state or times out.

        Periodically checks the job status and raises an exception if the
        job fails with an error or does not complete within the specified timeout.
        """
        LOG.info("RakutenCNSAPI._wait_job_completion()")

        start_time = time.time()
        while time.time() - start_time < TIMEOUT_JOB:
            job = self._get_job(jobid, debug)
            state = job["state"]
            error = job["error"]
            LOG.info("job state: %s, error: %s", state, error)

            if state == RakutenCNSJobState.COMPLETED.value:
                return
            
            if error:
                raise RakutenCNSException(f"Job {jobid} failed with error: {error}")
            
            time.sleep(1)

        raise RakutenCNSException(f"Job {jobid} did not complete within timeout")

    def _wait_for_volume_online_ready(self, name: str, debug: bool = False) -> None:
        """
        Wait for a volume to reach ONLINE status and READY state.

        Polls the volume status until it reaches the desired state or times out.
        """
        LOG.info("RakutenCNSAPI._wait_for_volume_online_ready()")

        start_time = time.time()
        while time.time() - start_time < TIMEOUT_VOLUME:
            get_request = {
                'name': name
            }

            response = self.volume_get(get_request, debug)
            items = response.get('items', {})
            if (items.get('state', 0) == RakutenCNSVolumeState.READY and
                items.get('status', 0) == RakutenCNSVolumeStatus.ONLINE):
                return

            time.sleep(1)

        raise RakutenCNSException(f"Volume {name} did not come up online and ready")

    def volume_create(self, body: dict, debug: bool = False) -> None:
        """
        Create a new volume on the Rakuten CNS backend.

        Sends a volume creation request to the CNS API, waits for the
        associated job to complete, and then verifies the volume is
        online and ready.
        """
        LOG.info("RakutenCNSAPI.volume_create()")

        data = self._api_call('POST', '/api/v6/robin_server/volumes', body, debug)
        if data.get("jobid"):
            self._wait_for_job_completion(data["jobid"], debug=debug)
            LOG.info("Volume creation job completed successfully")
            
            self._wait_for_volume_online_ready(body['name'], debug=debug)
            LOG.info("Volume %s is online and ready", body['name'])
        else:
            raise exception.VolumeBackendAPIException(data="volume create did not return jobid")
        
    def volume_mount(self, body: dict, debug: bool = False) -> str:
        """
        Mount a volume on the Rakuten CNS backend and return the mount path.

        Sends a volume mount request to the CNS API, waits for the
        associated job to complete, and then retrieves the mount path
        from the volume details.
        """
        LOG.info("RakutenCNSAPI.volume_mount()")

        data = self._api_call('PUT', '/api/v6/robin_server/volumes', body, debug)
        if data.get("jobid"):
            self._wait_for_job_completion(data["jobid"], debug=debug)
            LOG.info("Volume mount job completed successfully")
        elif data.get("allocated"):
            if data.get("allocated") == True:
                LOG.info("Volume mount job completed successfully")
            else:
                raise exception.VolumeBackendAPIException(data="volume mount failed, allocated: false")
        else:
            raise exception.VolumeBackendAPIException(data="volume mount did not return jobid")

        # Get the volume details to retrieve mount path
        get_request = {
            'name': body['name']
        }
        response = self.volume_get(get_request, debug)

        mounts = response.get('items', {}).get('mounts', [])
        mount_path = mounts[0].get('mntpath') if mounts else None

        if not mount_path:
            raise RakutenCNSException("Volume mount did not return mount path")
            
        return mount_path
        
    def volume_unmount(self, body: dict, debug: bool = False) -> None:
        """
        Unmount a volume on the Rakuten CNS backend.

        Sends a volume unmount request to the CNS API and waits for the
        associated job to complete.
        """
        LOG.info("RakutenCNSAPI.volume_unmount()")

        data = self._api_call('PUT', '/api/v6/robin_server/volumes', body, debug)
        if data.get("jobid"):
            self._wait_for_job_completion(data["jobid"], debug=debug)
            LOG.info("Volume unmount job completed successfully") 
        elif data.get("unmounted"):
            if data.get("unmounted") == True:
                LOG.info("Volume unmounted successfully")
            else:
                raise exception.VolumeBackendAPIException(data="volume unmount failed, unmounted: false")
        else:
            raise exception.VolumeBackendAPIException(data="volume unmount did not return jobid")

    def volume_delete(self, body: dict, debug: bool = False) -> None:
        """
        Delete a volume from the Rakuten CNS backend.

        Sends a volume deletion request to the CNS API and waits for the
        associated job to complete.
        """
        LOG.info("RakutenCNSAPI.volume_delete()")

        data = self._api_call('DELETE', '/api/v6/robin_server/volumes', body, debug)
        if data and data["jobid"]:
            self._wait_for_job_completion(data["jobid"], debug=debug)
            LOG.info("Volume deletion job completed successfully")
        else:
            raise exception.VolumeBackendAPIException(data="volume delete did not return jobid")
        
    def volume_get(self, body: dict, debug: bool = False) -> dict:
        """
        Retrieve details of a specific volume from the Rakuten CNS backend.

        Sends a GET request to the CNS API to fetch volume information
        based on the provided body parameters (e.g., volume name).
        """
        LOG.info("RakutenCNSAPI.volume_get()")

        return self._api_call('GET', f'/api/v6/robin_server/volumes', body, debug)

    def snapshot_create(self, body: dict, debug: bool = False):
        LOG.info("RakutenCNSAPI.snapshot_create()")

        data = self._api_call('POST', f'/api/v6/robin_server/volume-snapshots', body, debug)
        if data.get("jobid"):
            self._wait_for_job_completion(data["jobid"], debug=debug)
            LOG.info("Volume creation job completed successfully")            
        else:
            raise exception.VolumeBackendAPIException(data="snapshot create did not return jobid")

    def snapshot_delete(self, body: dict, debug: bool = False):
        LOG.info("RakutenCNSAPI.snapshot_delete()")

        data = self._api_call('DELETE', f'/api/v6/robin_server/volume-snapshots', body, debug)
        if data.get("jobid"):
            self._wait_for_job_completion(data["jobid"], debug=debug)
            LOG.info("Volume creation job completed successfully")            
        else:
            raise exception.VolumeBackendAPIException(data="snapshot delete did not return jobid")
    
    def disk_get_all(self, body: dict, debug: bool = False) -> dict:
        """
        Retrieve all disk information from the Rakuten CNS backend.

        Sends a GET request to the CNS API to fetch details about all
        disks in the storage cluster, including their roles, status,
        and capacity information.
        """
        LOG.info("RakutenCNSAPI.disk_get_all()")

        return self._api_call('GET', f'/api/v5/robin_server/disks', body, debug)


rakutencns_opts = [
    cfg.StrOpt('cns_username',
               default=None,
               help='The Rakuten CNS username for accessing the REST API.'),
    cfg.StrOpt('cns_password',
               default=None,
               help='The Rakuten CNS password for accessing the REST API.'),
]

CONF = cfg.CONF
CONF.register_opts(rakutencns_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class RakutenCNSDriver(driver.VolumeDriver):
    """
    OpenStack Cinder driver for Rakuten Cloud Native Storage (CNS).
    """
    
    VERSION = '0.1.0'
    CI_WIKI_NAME = 'Rakuten_CNS'

    def __init__(self, *args, **kwargs):
        super(RakutenCNSDriver, self).__init__(*args, **kwargs)
        self.backend_name = self.configuration.safe_get('volume_backend_name') or 'Rakuten CNS'
        self.configuration.append_config_values(rakutencns_opts)

        self._stats = None
        self._cns_api = None
        self._cns_username = self.configuration.safe_get('cns_username')
        self._cns_password = self.configuration.safe_get('cns_password')
        if not self._cns_username or not self._cns_password:
            raise exception.InvalidInput(reason="CNS username and password must be set")

    def _get_node_from_pod(self, name):
        """
        Get the node on which a given pod is running by querying the Kubernetes API.
        """
        with open(KUBERNETES_TOKEN_PATH, "r") as f:
            token = f.read().strip()

        url = f"{KUBERNETES_API_SERVER}/api/v1/namespaces/openstack/pods/{name}"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        response = requests.get(url, headers=headers, verify=KUBERNETES_CA_CERT_PATH)
        if response.status_code == 200:
            data = response.json()
            return data['spec']['nodeName']
        else:
            raise RakutenCNSException(f"Failed to get pod details: {response.status_code} {response.text}")

    def _os_to_cns_volume_name(self, id):
        """
        Convert an OpenStack volume ID to a CNS volume name.
        """
        return f"wro-vol-{id}"

    def _os_to_cns_snapshot_name(self, id):
        """
        Convert an OpenStack snapshot ID to a CNS snapshot name.
        """
        return f"wro-{id}"

    @staticmethod
    def get_driver_options():
        return rakutencns_opts

    def do_setup(self, context):
        """
        Perform any required one-time setup for the driver.

        Initializes the connection to the Rakuten CNS backend by creating
        an API client instance with the configured credentials.
        """
        LOG.info("RakutenCNSDriver.do_setup()")

        try:
            self._cns_api = RakutenCNSAPI(self._cns_username, self._cns_password)
        except Exception as e:
            raise exception.VolumeBackendAPIException(data="CNS service IP not found")

    def check_for_setup_error(self):
        """
        Verify that the driver setup completed successfully.

        Checks that the CNS API client was properly initialized during
        do_setup. Raises an exception if the backend is not ready.
        """
        if not self._cns_api:
            raise exception.VolumeBackendAPIException(data="CNS API client not initialized")

    def _create_volume(self, name: str, size: str):
        create_request = {
            'name': name,
            'size': size,
            'namespace': 'default',
            'protection': 'replication',
            'replication': '2'
        }

        try:
            self._cns_api.volume_create(create_request)
        except Exception as e:
            raise exception.VolumeBackendAPIException(data=str(e))

    def create_volume(self, volume):
        """
        Create a volume on the Rakuten CNS backend.

        Converts the OpenStack volume to a CNS volume creation request
        and sends it to the CNS API.
        """
        LOG.info("RakutenCNSDriver.create_volume()")

        try:
            self._create_volume(self._os_to_cns_volume_name(volume['id']), f"{volume['size']}G")
        except Exception as e:
            raise exception.VolumeBackendAPIException(data=str(e))
        
        return {'metadata': {}}

    def delete_volume(self, volume):
        """
        Delete a volume from the Rakuten CNS backend.

        Sends a volume deletion request to the CNS API.
        """
        LOG.info("RakutenCNSDriver.delete_volume()")

        delete_request = {
            'name': self._os_to_cns_volume_name(volume['id'])
        }

        try:
            self._cns_api.volume_delete(delete_request)
        except Exception as e:
            raise exception.VolumeBackendAPIException(data=str(e))

    def create_export(self, context, volume, connector):
        """
        Create an export for a volume by mounting it on the appropriate host.

        Determines the target hostname from the connector, resolving pod
        names to node names for glance-api and cinder-volume services,
        then mounts the volume on that host and returns the provider location.
        """
        LOG.info("RakutenCNSDriver.create_export()")

        hostname = connector['host']
        # On image creation, host = glance-api
        # On create volume from image, host = cinder-volume
        # On VM attach, host = compute node name
        if connector['host'].startswith("glance-api") or connector['host'].startswith("cinder-volume"):
            hostname = self._get_node_from_pod(connector['host'])

        mount_request = {
            "action": "mount",
            "name": self._os_to_cns_volume_name(volume['id']),
            "hostname": hostname
        }

        try:
            mount_path = self._cns_api.volume_mount(mount_request)
            LOG.info("Volume mount path: %s", mount_path)

            return {'provider_location': mount_path}
        except Exception as e:
            raise exception.VolumeBackendAPIException(data=str(e))

    def ensure_export(self, context, volume):
        """
        Ensure an export exists for a given volume.
        """
        LOG.info("RakutenCNSDriver.ensure_export()")
        pass

    def remove_export(self, context, volume):
        """
        Remove an export for a volume by unmounting it from the host.

        Retrieves the hostname from the export context or by querying the
        CNS API for mount information, then sends an unmount request.
        """
        LOG.info("RakutenCNSDriver.remove_export()")
        
        # Try to get where the volume is mounted if it's not stored in the context
        # (this is the case if cinder-volume is reloaded and volumes were created)
        remove_request = {
            'name': self._os_to_cns_volume_name(volume['id'])
        }

        response = self._cns_api.volume_get(remove_request)

        mounts = response.get('items', {}).get('mounts', [])
        hostname = mounts[0].get('nodename') if mounts else None

        if not hostname:
            # It's possible that the volume is not mounted (for e.g., volume was created and not attached to a VM),
            # in this case continue silently.
            return

        unmount_request = {
            'action': 'unmount',
            'name': self._os_to_cns_volume_name(volume['id']),
            'hostname': hostname
        }

        try:
            self._cns_api.volume_unmount(unmount_request)
        except Exception as e:
            raise exception.VolumeBackendAPIException(data=str(e))

    def retype(self, context, volume, new_type, diff, host):
        raise NotImplementedError

    def migrate_volume(self, ctxt, volume, host, thin=False, mirror_count=0):
        raise NotImplementedError

    def create_snapshot(self, snapshot):
        """
        Create a snapshot.
        """
        LOG.info("RakutenCNSDriver.create_snapshot()")
        
        snapshot_request = {
            'action': 'snapshot',
            'name': self._os_to_cns_volume_name(snapshot.volume_name),
            'snapname': self._os_to_cns_snapshot_name(snapshot.name)
        }

        try:
            response = self._cns_api.snapshot_create(snapshot_request)
        except Exception as e:
            raise exception.VolumeBackendAPIException(data=str(e))

    def delete_snapshot(self, snapshot):
        """
        Delete a snapshot.
        """
        LOG.info("RakutenCNSDriver.delete_snapshot()")

        snapshot_request = {
            'snapname': self._os_to_cns_snapshot_name(snapshot.name)
        }

        try:
            response = self._cns_api.snapshot_delete(snapshot_request)
        except Exception as e:
            raise exception.VolumeBackendAPIException(data=str(e))

    
    def create_volume_from_snapshot(self, volume, snapshot):
        """
        Create a volume from a snapshot.
        """
        LOG.info("RakutenCNSDriver.create_volume_from_snapshot()")
        raise NotImplementedError

    def create_cloned_volume(self, volume, src_vref):
        """
        Create a clone of an existing volume.
        """
        raise NotImplementedError

    def extend_volume(self, volume, new_size):
        """
        Extend an existing volume's size.
        """
        LOG.info("RakutenCNSDriver.extend_volume()")
        raise NotImplementedError

    def _update_volume_stats(self):
        """
        Retrieve volume statistics from the Rakuten CNS backend.

        Queries the CNS API for disk information and calculates total
        and free capacity based on online, ready storage disks.
        """
        try:
            disks = self._cns_api.disk_get_all({})
        except Exception as e:
            raise exception.VolumeBackendAPIException(data=str(e))

        total_capacity_gb = 0
        free_capacity_gb = 0
        for disk in disks.get('items', []):
            # TODO: Enum instead of hard coded values
            if disk.get("role") == "Storage" and disk.get("status") == "ONLINE" and disk.get("state") == "READY":
                total_capacity_gb += disk.get("max_alloc_slices")
                free_capacity_gb += disk.get("free_alloc_slices")

        return {
            'volume_backend_name': self.backend_name,
            'vendor_name': 'Rakuten CNS',
            'driver_version': self.VERSION,
            'storage_protocol': 'local',
            'total_capacity_gb': total_capacity_gb,
            'free_capacity_gb': free_capacity_gb,
            'reserved_percentage': 0,
            'QoS_support': False,
            'thick_provisioning_support': False,
            'thin_provisioning_support': True,
        }

    def get_volume_stats(self, refresh=False):
        """
        Get volume stats.
        If 'refresh' is True, run update the stats first.
        """
        if not self._stats or refresh:
            return self._update_volume_stats()

    def initialize_connection(self, volume, connector):
        """
        Initialize a connection to a volume and return connection info.
        """
        LOG.info("RakutenCNSDriver.initialize_connection()")

        return {
            'driver_volume_type': 'local',
            'data': {
                'device_path': volume['provider_location'],
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """
        Terminate a connection to a volume.
        """
        LOG.info("RakutenCNSDriver.terminate_connection()")
        pass