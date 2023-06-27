from airflow.models import DAG
from operators.mattermost import MattermostOperator
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from datetime import timedelta
import requests
from datagouvfr_data_pipelines.config import (
    MATTERMOST_DATAGOUV_MOISSONNAGE,
    DATAGOUV_SECRET_API_KEY,
)

DAG_NAME = "dgv_harvester_notification"
PAD_AWAITING_VALIDATION = "https://pad.incubateur.net/173bEiKKTi2laBNyHwIPlQ"

default_args = {"email": ["geoffrey.aldebert@data.gouv.fr"], "email_on_failure": True}


def get_pending_harvester_from_api(ti):
    page = 1
    r = requests.get(
        "https://www.data.gouv.fr/api/1/harvest/sources/?page=" + str(page)
    )
    maxpage = int(r.json()["total"] / r.json()["page_size"]) + 1
    arr = []
    cpt = 0
    page = 0
    for i in range(maxpage):
        r = requests.get(
            "https://www.data.gouv.fr/api/1/harvest/sources/?page=" + str(page + 1)
        )
        print("https://www.data.gouv.fr/api/1/harvest/sources/?page=" + str(page + 1))
        r.raise_for_status()
        for d in r.json()["data"]:
            cpt = cpt + 1
            if d["validation"]["state"] == "pending":
                mydict = {}
                mydict["admin_url"] = (
                    "https://www.data.gouv.fr/fr/admin/harvester/" + d["id"]
                )
                mydict["name"] = d["name"]
                mydict["url"] = d["url"]
                if d["organization"]:
                    mydict["orga"] = "Organisation " + d["organization"]["name"]
                    mydict["orga_url"] = (
                        "https://www.data.gouv.fr/fr/organizations/"
                        + d["organization"]["id"]
                    )
                if d["owner"]:
                    mydict["orga"] = (
                        "Utilisateur "
                        + d["owner"]["first_name"]
                        + " "
                        + d["owner"]["last_name"]
                    )
                    mydict["orga_url"] = (
                        "https://www.data.gouv.fr/fr/users/" + d["owner"]["id"]
                    )
                if "orga" not in mydict:
                    mydict["orga"] = "Utilisateur inconnu"
                    mydict["orga_url"] = ""
                mydict["id"] = d["id"]
                arr.append(mydict)
        page = page + 1
    ti.xcom_push(key="list_pendings", value=arr)


def get_preview_state_from_api(ti):
    list_pendings = ti.xcom_pull(key="list_pendings", task_ids="get_pending_harvester")

    headers = {"X-API-KEY": DATAGOUV_SECRET_API_KEY}
    for item in list_pendings:
        try:
            r = requests.get(
                "https://www.data.gouv.fr/api/1/harvest/source/{}/preview".format(
                    item["id"]
                ),
                timeout=60,
                headers=headers,
            )
            print(r.json())
            item["preview"] = r.json()["status"]
        except:
            print("error on " + item["id"])
            item["preview"] = "timeout"

    ti.xcom_push(key="list_pendings_complete", value=list_pendings)


def publish_mattermost_harvester(ti):
    list_pendings = ti.xcom_pull(
        key="list_pendings_complete", task_ids="get_preview_state"
    )

    list_pendings_done = [lp for lp in list_pendings if lp["preview"] == "done"]
    list_pendings_failed = [lp for lp in list_pendings if lp["preview"] == "failed"]
    list_pendings_timeout = [lp for lp in list_pendings if lp["preview"] == "timeout"]
    list_pendings_other = [
        lp for lp in list_pendings if lp["preview"] not in ["timeout", "done", "failed"]
    ]

    text = (
        ":mega: Rapport hebdo sur l'état des moissonneurs en attente : \n "
        f"- {len(list_pendings)} moissonneurs en attente \n "
        f"- {len(list_pendings_done)} moissonneurs en attente dont la preview fonctionne \n "
        f"- {len(list_pendings_timeout)} moissonneurs en attente dont la preview n'aboutit pas "
        "(timeout de 60 secondes) \n "
        f"- {len(list_pendings_failed)} moissonneurs en attente dont la preview failed \n "
        f"- {len(list_pendings_other)} moissonneurs dont la preview est dans un autre statut "
        "\n \n\nListe des moissonneurs en pending dont la preview fonctionne : \n"
    )

    for lp in list_pendings_done:
        print(lp)
        text = (
            text
            + " - [{}]({}) - Moissonneur [{}]({}) - Lien vers [l'espace Admin]({}) \n".format(
                lp["orga"], lp["orga_url"], lp["name"], lp["url"], lp["admin_url"]
            )
        )

    text = (
        text
        + "\nListe des moissonneurs en attente dont la preview n'aboutit pas (timeout de 60 secondes) : \n"
    )

    for lp in list_pendings_timeout:
        print(lp)
        text = (
            text
            + " - [{}]({}) - Moissonneur [{}]({}) - Lien vers [l'espace Admin]({}) \n".format(
                lp["orga"], lp["orga_url"], lp["name"], lp["url"], lp["admin_url"]
            )
        )

    text = text + "\nListe des moissonneurs en attente dont la preview failed : \n"

    for lp in list_pendings_failed:
        text = (
            text
            + " - [{}]({}) - Moissonneur [{}]({}) - Lien vers [l'espace Admin]({}) \n".format(
                lp["orga"], lp["orga_url"], lp["name"], lp["url"], lp["admin_url"]
            )
        )

    text = text + "\nListe des moissonneurs en pending avec un autre statut : \n"

    for lp in list_pendings_other:
        text = (
            text
            + " - [{}]({}) - Moissonneur [{}]({}) - Lien vers [l'espace Admin]({}) \n".format(
                lp["orga"], lp["orga_url"], lp["name"], lp["url"], lp["admin_url"]
            )
        )

    text = (
        f"{text}Avant validation, pensez à consulter [le pad des moissonneurs à laisser "
        f"en attente de validation]({PAD_AWAITING_VALIDATION}) \n"
    )

    send_notif = MattermostOperator(
        task_id="publish_result",
        mattermost_endpoint=MATTERMOST_DATAGOUV_MOISSONNAGE,
        text=text,
    )
    print(text)
    send_notif.execute(dict())


with DAG(
    dag_id=DAG_NAME,
    schedule_interval="0 9 * * WED",
    start_date=days_ago(8),
    dagrun_timeout=timedelta(minutes=60),
    tags=["weekly", "harvester", "mattermost", "notification"],
    default_args=default_args,
    catchup=False,
) as dag:
    get_pending_harvester = PythonOperator(
        task_id="get_pending_harvester",
        python_callable=get_pending_harvester_from_api,
    )

    get_preview_state = PythonOperator(
        task_id="get_preview_state",
        python_callable=get_preview_state_from_api,
    )

    publish_mattermost = PythonOperator(
        task_id="publish_mattermost",
        python_callable=publish_mattermost_harvester,
    )

    get_preview_state.set_upstream(get_pending_harvester)
    publish_mattermost.set_upstream(get_preview_state)
