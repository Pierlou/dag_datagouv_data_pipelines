from airflow.models import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from datetime import timedelta
from datagouvfr_data_pipelines.config import (
    AIRFLOW_DAG_HOME,
    AIRFLOW_DAG_TMP,
)

from datagouvfr_data_pipelines.data_processing.elections.task_functions import (
    get_files_minio_mirroring,
)

TMP_FOLDER = f"{AIRFLOW_DAG_TMP}elections-mirroring/"
DAG_FOLDER = 'datagouvfr_data_pipelines/data_processing/'
DAG_NAME = 'data_mirroring_elections'
DATADIR = f"{AIRFLOW_DAG_TMP}elections-mirroring/data"

default_args = {
    'email': [
        'pierlou.ramade@data.gouv.fr',
        'geoffrey.aldebert@data.gouv.fr'
    ],
    'email_on_failure': False
}

with DAG(
    dag_id=DAG_NAME,
    schedule_interval='15 7 1 1 *',
    start_date=days_ago(1),
    catchup=False,
    dagrun_timeout=timedelta(minutes=240),
    tags=["data_processing", "election", "miroir", "miom"],
    default_args=default_args,
) as dag:

    clean_previous_outputs = BashOperator(
        task_id="clean_previous_outputs",
        bash_command=f"rm -rf {TMP_FOLDER} && mkdir -p {TMP_FOLDER}",
    )

    get_files_minio_mirroring = PythonOperator(
        task_id='get_files_minio_mirroring',
        python_callable=get_files_minio_mirroring,
    )

    get_files_minio_mirroring.set_upstream(clean_previous_outputs)
