"""Budget kill switch: disables billing on the project once cost reaches the budget.

Deployed as a Cloud Run function subscribed to the budget's Pub/Sub topic
(see deploy/setup_gcp.sh). Disabling billing stops every paid service in the
project -- Cloud Run, Cloud Build, Secret Manager -- so the POC can never cost
more than roughly the budget amount. Re-enable billing manually in the console
after investigating.

Note: budget notifications lag real usage by up to a few hours, so the
actual spend can slightly exceed the budget before this fires.

Set DRY_RUN=true to log the decision without touching billing (used to test).
A dry run also verifies the service account holds the permission needed to
unlink billing, so the test proves the real switch would work.
"""

import base64
import json
import os

import functions_framework
from googleapiclient import discovery

PROJECT_ID = os.environ["PROJECT_ID"]
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


def should_disable(notification: dict) -> bool:
    """True once the reported cost has reached the budget amount."""
    cost = float(notification.get("costAmount", 0))
    budget = float(notification.get("budgetAmount", 0))
    return budget > 0 and cost >= budget


UNLINK_PERMISSION = "resourcemanager.projects.deleteBillingAssignment"


def _can_unlink_billing() -> bool:
    crm = discovery.build("cloudresourcemanager", "v1", cache_discovery=False)
    granted = crm.projects().testIamPermissions(
        resource=PROJECT_ID, body={"permissions": [UNLINK_PERMISSION]}
    ).execute()
    return UNLINK_PERMISSION in granted.get("permissions", [])


def _billing_enabled(billing, project_name: str) -> bool:
    info = billing.projects().getBillingInfo(name=project_name).execute()
    return bool(info.get("billingEnabled"))


@functions_framework.cloud_event
def stop_billing(cloud_event) -> None:
    payload = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    notification = json.loads(payload)
    cost, budget = notification.get("costAmount"), notification.get("budgetAmount")

    if not should_disable(notification):
        print(f"[killswitch] cost {cost} < budget {budget}: nothing to do")
        return

    project_name = f"projects/{PROJECT_ID}"
    billing = discovery.build("cloudbilling", "v1", cache_discovery=False)
    if not _billing_enabled(billing, project_name):
        print("[killswitch] billing already disabled")
        return

    if DRY_RUN:
        verdict = "OK" if _can_unlink_billing() else f"MISSING {UNLINK_PERMISSION}"
        print(
            f"[killswitch] DRY_RUN: would disable billing (cost {cost} >= budget {budget}); "
            f"unlink permission: {verdict}"
        )
        return

    billing.projects().updateBillingInfo(
        name=project_name, body={"billingAccountName": ""}
    ).execute()
    print(f"[killswitch] BILLING DISABLED for {PROJECT_ID} (cost {cost} >= budget {budget})")
