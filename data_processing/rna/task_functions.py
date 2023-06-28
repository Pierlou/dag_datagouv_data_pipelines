from airflow.hooks.base import BaseHook
from datagouvfr_data_pipelines.config import (
    AIRFLOW_DAG_HOME,
    AIRFLOW_DAG_TMP,
    DATAGOUV_SECRET_API_KEY,
    AIRFLOW_ENV,
    MINIO_URL,
    MINIO_BUCKET_DATA_PIPELINE_OPEN,
    SECRET_MINIO_DATA_PIPELINE_USER,
    SECRET_MINIO_DATA_PIPELINE_PASSWORD,
)
from datagouvfr_data_pipelines.utils.postgres import execute_sql_file, copy_file
from datagouvfr_data_pipelines.utils.datagouv import post_remote_communautary_resource
from datagouvfr_data_pipelines.utils.mattermost import send_message
from datagouvfr_data_pipelines.utils.minio import send_files
import pandas as pd
import os
from datetime import datetime
from unidecode import unidecode

DAG_FOLDER = "datagouvfr_data_pipelines/data_processing/"
DATADIR = f"{AIRFLOW_DAG_TMP}rna/data"
SQLDIR = f"{AIRFLOW_DAG_TMP}rna/sql"

if AIRFLOW_ENV == "prod":
    DATAGOUV_URL = "https://www.data.gouv.fr"
    conn = BaseHook.get_connection("POSTGRES_DEV")
else:
    DATAGOUV_URL = "https://demo.data.gouv.fr"
    conn = BaseHook.get_connection("postgres_localhost")


def process_rna():
    # concatenate all files
    df_rna = pd.DataFrame(None)
    for f in sorted(os.listdir(os.path.join(DATADIR, "rna"))):
        print(f)
        _ = pd.read_csv(
            os.path.join(DATADIR, "rna", f), sep=";", encoding="ISO-8859-1", dtype=str
        )
        df_rna = pd.concat([df_rna, _])
    punc_to_remove = "!\"#$%&'()*+/;?@[]^_`{|}~"
    for c in df_rna.columns:
        df_rna[c] = df_rna[c].apply(
            lambda s: unidecode(s)
            .translate(str.maketrans("", "", punc_to_remove))
            .encode("unicode-escape")
            .decode()
            .replace("\\", "")
            if isinstance(s, str)
            else s
        )
    # export to csv
    df_rna.to_csv(os.path.join(DATADIR, "base_rna.csv"), index=False, encoding="utf8")


def create_rna_table():
    execute_sql_file(
        conn.host,
        conn.port,
        conn.schema,
        conn.login,
        conn.password,
        [
            {
                "source_path": f"{AIRFLOW_DAG_HOME}{DAG_FOLDER}rna/sql/",
                "source_name": "create_rna_table.sql",
            }
        ],
    )


def populate_utils(files, table):
    format_files = []
    for file in files:
        format_files.append(
            {"source_path": f"{DATADIR}/", "source_name": file.split("/")[-1]}
        )
    copy_file(
        PG_HOST=conn.host,
        PG_PORT=conn.port,
        PG_DB=conn.schema,
        PG_TABLE=table,
        PG_USER=conn.login,
        PG_PASSWORD=conn.password,
        list_files=format_files,
    )


def populate_rna_table():
    if AIRFLOW_ENV == "prod":
        populate_utils([f"{DATADIR}/base_rna.csv"], "airflow.base_rna")
    else:
        populate_utils([f"{DATADIR}/base_rna.csv"], "base_rna")


def index_rna_table():
    execute_sql_file(
        conn.host,
        conn.port,
        conn.schema,
        conn.login,
        conn.password,
        [
            {
                "source_path": f"{AIRFLOW_DAG_HOME}{DAG_FOLDER}rna/sql/",
                "source_name": "index_rna_table.sql",
            }
        ],
    )


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


def publish_rna_communautaire():
    file_size = os.path.getsize(os.path.join(DATADIR, "base_rna.csv"))
    if AIRFLOW_ENV == "prod":
        # data.gouv.fr
        orga_id = "646b7187b50b2a93b1ae3d45"
    else:
        # DataTeam
        orga_id = "63e3ae4082ddaa6c806b8417"
    post_remote_communautary_resource(
        api_key=DATAGOUV_SECRET_API_KEY,
        dataset_id="58e53811c751df03df38f42d",
        title="RNA agrégé",
        format="csv",
        remote_url=f"https://object.files.data.gouv.fr/{MINIO_BUCKET_DATA_PIPELINE_OPEN}/{AIRFLOW_ENV}/rna/base_rna.csv",
        organisation_publication_id=orga_id,
        filesize=file_size,
        description=f"Répertoire National des Associations en un seul fichier, agrégé à partir des données brutes ({datetime.now()})",
    )


def send_notification_mattermost(ti):
    send_message(
        text=(
            ":mega: Données des associations mises à jour.\n"
            f"- Données stockées sur Minio - Bucket {MINIO_BUCKET_DATA_PIPELINE_OPEN}\n"
            f"- Données publiées [sur data.gouv.fr]({DATAGOUV_URL}/fr/datasets/58e53811c751df03df38f42d)"
        )
    )
