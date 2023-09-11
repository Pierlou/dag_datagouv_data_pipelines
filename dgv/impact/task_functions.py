from airflow.hooks.base import BaseHook
from datagouvfr_data_pipelines.config import (
    AIRFLOW_DAG_TMP,
    DATAGOUV_SECRET_API_KEY,
    AIRFLOW_ENV,
    MINIO_URL,
    MINIO_BUCKET_DATA_PIPELINE_OPEN,
    SECRET_MINIO_DATA_PIPELINE_USER,
    SECRET_MINIO_DATA_PIPELINE_PASSWORD,
)
from datagouvfr_data_pipelines.utils.mattermost import send_message
from datagouvfr_data_pipelines.utils.minio import send_files
from datagouvfr_data_pipelines.utils.datagouv import get_all_from_api_query
import pandas as pd
import os
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import numpy as np

DAG_FOLDER = "datagouvfr_data_pipelines/data_processing/"
DATADIR = f"{AIRFLOW_DAG_TMP}impact/data"


def calculate_metrics():
    # quality score
    df_datasets = pd.read_csv(
        "https://www.data.gouv.fr/fr/datasets/r/f868cca6-8da1-4369-a78d-47463f19a9a3",
        dtype=str,
        sep=";"
    )
    df_datasets["metric.views"] = df_datasets["metric.views"].astype(float)
    df_datasets = df_datasets.sort_values(by="metric.views", ascending=False)
    final = df_datasets[:1000]
    final["quality_score"] = final["quality_score"].astype(float)
    average_quality_score = round(100 * final["quality_score"].mean(), 2)

    # response time
    r = get_all_from_api_query("https://www.data.gouv.fr/api/1/discussions/")
    oneyearago = date.today() - relativedelta(years=1)
    oneyearago = oneyearago.strftime("%Y-%m-%d")
    nb_discussions = 0
    nb_discussions_with_answer = 0
    time_to_answer = []
    actual_date = date.today().strftime("%Y-%m-%d")
    while actual_date > oneyearago:
        item = next(r)
        actual_date = item["discussion"][0]["posted_on"]
        if actual_date > oneyearago and item["subject"]["class"] == "Dataset":
            nb_discussions += 1
            if len(item["discussion"]) > 1:
                nb_discussions_with_answer += 1
                date_format = "%Y-%m-%dT%H:%M:%S" 
                first_date = datetime.strptime(item["discussion"][0]["posted_on"][:19], date_format)
                second_date = datetime.strptime(item["discussion"][1]["posted_on"][:19], date_format)
                ecart = second_date - first_date
                ecart_jour = ecart.days + (ecart.seconds / (3600 * 24))
                if ecart_jour > 30:
                    time_to_answer.append(30)
                else:
                    time_to_answer.append(ecart_jour)
            else:
                time_to_answer.append(30)
    average_time_to_answer = np.mean(time_to_answer)

    data = [
        {
            'nom_service_public_numerique': 'data.gouv.fr',
            'indicateur': 'Score qualité moyen 1000 JdD les plus vus',
            'valeur': average_quality_score,
            'unite_mesure': 'unité',
            'est_cible': False,
            'frequence_calcul': 'mensuelle',
            'date': datetime.today().strftime("%Y-%m-%d"),
            'est_periode': False,
            'date_debut': '',
            'est_automatise': True,
            'source_collecte': 'script',
            'mode_calcul': 'moyenne',
            'commentaires': ''
        },
        {
            'nom_service_public_numerique': 'data.gouv.fr',
            'indicateur': 'Délai moyen de réponse à une discussion',
            'valeur': average_time_to_answer,
            'unite_mesure': 'jour',
            'est_cible': False,
            'frequence_calcul': 'mensuelle',
            'date': datetime.today().strftime("%Y-%m-%d"),
            'est_periode': True,
            'date_debut': oneyearago,
            'est_automatise': True,
            'source_collecte': 'script',
            'mode_calcul': 'moyenne',
            'commentaires': ''
        },
    ]
    df = pd.DataFrame(data)
    ## créer un fichier vide sur minio, aller le chercher, concaténer et repush sur un autre (pour l'instant)
    df.to_csv(os.path.join(DATADIR, "impact.csv"), index=False, encoding="utf8")


def send_rna_to_minio():
    send_files(
        MINIO_URL=MINIO_URL,
        MINIO_BUCKET=MINIO_BUCKET_DATA_PIPELINE_OPEN,
        MINIO_USER=SECRET_MINIO_DATA_PIPELINE_USER,
        MINIO_PASSWORD=SECRET_MINIO_DATA_PIPELINE_PASSWORD,
        list_files=[
            {
                "source_path": f"{DATADIR}/",
                "source_name": "base_rna.csv",
                "dest_path": "rna/",
                "dest_name": "base_rna.csv",
            }
        ],
    )


def send_notification_mattermost(ti):
    send_message(
        text=(
            ":mega: Données des associations mises à jour.\n"
            f"- Données stockées sur Minio - Bucket {MINIO_BUCKET_DATA_PIPELINE_OPEN}\n"
            # f"- Données publiées [sur data.gouv.fr]({DATAGOUV_URL}/fr/datasets/XXXXXXXXXXXX)"
        )
    )
