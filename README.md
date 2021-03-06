# Coastal Wind and Water Event Database (CWWED)

https://www.weather.gov/sti/coastalact_cwwed

## Development & Initial Setup

### Python Environment (>=3.6)

    # create the python environment
    mkvirtualenv cwwed-env
    
    # install requirements
    pip install -r requirements.txt
    
    # activate environment if in a new shell
    workon cwwed-env

### Running via Docker Compose
   
    # start PostGIS/OPeNDAP/RabbitMQ via Docker
    docker-compose up
    
    # start server
    python manage.py runserver
    
    # start Celery and Flower (celery web management)
    python manage.py celery
    
Initial Setup

    # migrate/create tables
    python manage.py migrate
    
    # create super user
    python manage.py createsuperuser
    
    # load dev data
    python manage.py loaddata dev-db.json

    # create "nsem" user & model permissions
    python manage.py cwwed-init
    
    
Collect Covered Data

    python manage.py collect_covered_data
    
##### Helpers

Purge RabbitMQ

    docker-compose exec rabbitmq rabbitmqctl purge_queue celery
    
Purge Celery

    celery -A cwwed purge -f
    
    
### Running via Kubernetes

Using [Minikube](https://github.com/kubernetes/minikube) for local cluster.

    # start cluster in vm
    # NOTE: this automatically configures the docker & kubectl environments to point to the minikube cluster
    minikube start --memory 8192
    
    # run if you want the docker & kubectl environments in a different terminal
    eval $(minikube docker-env)
    kubectl config use-context minikube
    
    # build images
    docker build -t cwwed-app .
    
    # create secrets
    # NOTE: always create new secrets with `echo -n "SECRET"` to avoid newline characters
    # NOTE: when updating, you need to either patch it (https://stackoverflow.com/a/45881259) or delete & recreate: `kubectl delete secret cwwed-secrets`
    kubectl create secret generic cwwed-secrets \
        --from-literal=CWWED_NSEM_PASSWORD=$(cat ~/Documents/cwwed/secrets/cwwed_nsem_password.txt) \
        --from-literal=SECRET_KEY=$(cat ~/Documents/cwwed/secrets/secret_key.txt) \
        --from-literal=SLACK_BOT_TOKEN=$(cat ~/Documents/cwwed/secrets/slack_bot_token.txt) \
        --from-literal=DATABASE_URL=$(cat ~/Documents/cwwed/secrets/database_url.txt) \
        --from-literal=CWWED_ARCHIVES_ACCESS_KEY_ID=$(cat ~/Documents/cwwed/secrets/cwwed_archives_access_key_id.txt) \
        --from-literal=CWWED_ARCHIVES_SECRET_ACCESS_KEY=$(cat ~/Documents/cwwed/secrets/cwwed_archives_secret_access_key.txt) \
        --from-literal=CELERY_FLOWER_USER=$(cat ~/Documents/cwwed/secrets/celery_flower_user.txt) \
        --from-literal=CELERY_FLOWER_PASSWORD=$(cat ~/Documents/cwwed/secrets/celery_flower_password.txt) \
        --from-literal=EMAIL_HOST_PASSWORD=$(cat ~/Documents/cwwed/secrets/sendgrid-api-key.txt) \
        --from-literal=SENTRY_DSN=$(cat ~/Documents/cwwed/secrets/sentry_dsn.txt) \
        && true
    
    # create everything all at once (in the right order: services, local volumes then deployments)
    ls -1 configs/local_service-*.yml configs/service-*.yml configs/local_volume-* configs/local_deployment-* configs/deployment-* | xargs -L 1 kubectl apply -f
    
    # delete everything
    ls -1 configs/*.yml | xargs -L 1 kubectl delete -f
    
    # create services individually
    kubectl apply -f configs/service-cwwed.yml
    kubectl apply -f configs/local_service-postgis.yml
    kubectl apply -f configs/service-opendap.yml
    kubectl apply -f configs/service-rabbitmq.yml
    kubectl apply -f configs/service-celery-flower.yml
    
    # create volumes individually
    kubectl apply -f configs/local_volume-cwwed.yml
    kubectl apply -f configs/local_volume-postgis.yml
    
    # create deployments individually
    kubectl apply -f configs/deployment-cwwed.yml
    kubectl apply -f configs/deployment-opendap.yml
    kubectl apply -f configs/deployment-rabbitmq.yml
    kubectl apply -f configs/deployment-celery.yml
    kubectl apply -f configs/deployment-celery-flower.yml
    kubectl apply -f configs/local_deployment-postgis.yml
    
    # get pod name
    CWWED_POD=$(kubectl get pods -l app=cwwed-container --no-headers -o custom-columns=:metadata.name)
    
    # connect to pod
    kubectl exec -it $CWWED_POD bash
    
    # initializations
    kubectl exec -it $CWWED_POD python manage.py migrate
    kubectl exec -it $CWWED_POD python manage.py createsuperuser
    kubectl exec -it $CWWED_POD python manage.py cwwed-init
    kubectl exec -it $CWWED_POD python manage.py loaddata dev-db.json
    
    # alternatively exectute commands from local environment using production settings
    DATABASE_URL=$(cat ~/Documents/cwwed/secrets/database_url.txt) DEPLOY_STAGE=prod python manage.py dbshell
    
    # collect covered data
    kubectl exec -it $CWWED_POD python manage.py collect_covered_data
    
    # get minikube/vm cwwed url
    minikube service cwwed-app-service --url
    
    # get minikube/vm celery/flower url
    minikube service celery-flower-service --url
    
    # delete minikube cluster
    minikube delete
    
#### Monitoring

*NOTE: This takes up a lot of resources and is not in use.*

Monitoring via Prometheus/Grafana.
[Install](https://github.com/coreos/prometheus-operator/tree/master/contrib/kube-prometheus) by checking out repository and applying the included manifests.

User:admin

    # port forward grafana to local
    kubectl port-forward $(kubectl get pods -l app=grafana -n monitoring --output=jsonpath="{.items..metadata.name}") -n monitoring 3000
    
### Build front-end app

    # copies output to a sub-folder which django includes as a "static" directory
    npm --prefix frontend run build-prod
    
## Production *-TODO-*
Setup RDS with proper VPC and security group permissions.

EFS:
- Create EFS instance
- Assign EFS security group to EC2 instance(s).  (TODO - figure out how auto scaling default security groups work)

Environment variables
- `SECRET_KEY`
- `DJANGO_SETTINGS_MODULE`
- `DATABASE_URL`
- `SLACK_BOT_TOKEN`
- `CWWED_NSEM_PASSWORD`

Configure Django "Sites" (in admin)

    For example, log into the admin and create a site as `dev.cwwed-staging.com`.
    
Create AWS user *cwwed-archives* and assign the following polices:
 - `configs/aws/s3-policy-cwwed-archives.json` and they'll be able read/write `s3://cwwed-archives/`.
    
Create Kubernetes cluster via [kops](https://github.com/kubernetes/kops).

    # create cluster (dev)
    kops create cluster --master-count 1 --node-count 2 --master-size t2.medium --node-size t2.medium --zones us-east-1a --name cwwed-dev-cluster.k8s.local --state=s3://cwwed-kops-state --yes
    
    # (if necessary) configure kubectl environment to point at aws cluster
    kops export kubecfg --name cwwed-dev-cluster.k8s.local --state=s3://cwwed-kops-state
    
    # create secrets (REFER to secrets in dev instructions)
    
    # create EFS and make sure it's in the same VPC as the cluster, along with the node's security group
    
    # create efs volume (can take a couple minutes to create the provisioner pod)
    # https://github.com/kubernetes-incubator/external-storage/tree/master/aws/efs
    kubectl apply -f configs/volume-efs.yml
    # patch (after RBAC stuff)
    kubectl patch deployment efs-provisioner -p '{"spec":{"template":{"spec":{"serviceAccount":"efs-provisioner"}}}}'
    
#### Load Balancing

Install [Ambassador](https://www.getambassador.io) for load balancing.

It avoids AWS's $20/month Elastic Load Balancing services which we would need for each exposed service.

    kubectl apply -f configs/ambassador-rbac.yaml
    kubectl apply -f configs/service-ambassador.yml
    
Monitor the new external Load Balancer and get it's external IP address.

    kubectl get service -o wide
    
Use that IP and configure DNS via Cloudflare.


#### Install all the services, volumes, deployments etc.
    
    # create everything all at once (in the right order: services, volumes then deployments)
    ls -1 configs/service-*.yml configs/volume-* configs/deployment-* | xargs -L 1 kubectl apply -f
    
    # patch the persistent volume to "retain" rather than delete if the claim is deleted
    # https://kubernetes.io/docs/tasks/administer-cluster/change-pv-reclaim-policy/
    kubectl patch pv XXX -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
    
#### Helpers
    
    # collect covered data via job
    kubectl apply -f configs/job-collect-covered-data.yml
    
    # force a rolling update (to repull images)
    kubectl patch deployment cwwed-deployment -p "{\"spec\":{\"template\":{\"metadata\":{\"labels\":{\"date\":\"`date +'%s'`\"}}}}}"
    
    # generate new api token for a user
    CWWED_POD=$(kubectl get pods -l app=cwwed-container --no-headers -o custom-columns=:metadata.name)
    kubectl exec -it ${CWWED_POD} -- python manage.py drf_create_token -r ${API_USER}
    
#### Celery dashboard (Flower)

    - Go to the configured domain in Cloudflare
    - Use the user/password saved in the secrets file
   
#### Kubernetes Dashboard
    
    # create kubernetes dashboard
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/master/src/deploy/recommended/kubernetes-dashboard.yaml
    
    # apply user/roles
    kubectl apply -f configs/kube-service-account.yml
    kubectl apply -f configs/kube-cluster-role-binding.yml
    
    # get token
    kubectl -n kube-system describe secret $(kubectl -n kube-system get secret | grep admin | awk '{print $1}')
    
    # start proxy
    kubectl proxy

    
## NSEM process

Submit a new NSEM request using the user's generated token:

    curl -sH "Authorization: Token aca89a70c8fa67144109b368b2b9994241bdbf2c" -H "Content-Type: application/json" -d '{"named_storm": "1"}' http://127.0.0.1:8000/api/nsem/
    {
        "id":76,
        "covered_data_storage_url": null,
        "date_requested": "2018-05-09T17:25:42.695051Z",
        "date_returned": null, 
        "covered_data_snapshot": "",
        "model_output_snapshot": "",
        "model_output_snapshot_extracted": false,
        "named_storm": 1,
    }
    
The `covered_data_storage_url` in the response will initially be empty, but a background process will have been initiated and eventually populate the AWS S3 bucket which you'll download the covered data from.

Wait a few minutes and re-query the "nsem" record to see if `covered_data_storage_url` has been populated.

    curl -sH "Content-Type: application/json" http://127.0.0.1:8000/api/nsem/76/
    
    {
        "id": 76,
        "covered_data_storage_url": "s3://cwwed-archives/NSEM/Harvey/v76/Covered Data",
        "date_requested": "2018-05-09T17:48:22.583653Z",
        "date_returned": "2018-05-09T18:02:28.497192Z",
        "covered_data_snapshot": "NSEM/Harvey/v76/Covered Data",
        "model_output_snapshot": "NSEM/Harvey/v76/Post Storm Assessment/v76.tgz",
        "model_output_snapshot_extracted": true,
        "named_storm": 1
    }

Download the covered data snapshot for an NSEM record:

    aws s3 cp --recursive "s3://cwwed-archives/NSEM/Harvey/v76/Covered Data" /YOUR/OUTPUT/PATH --profile nsem
    
Upload model output for a specific NSEM record:

*NOTE: The input format must be tar+gzipped and named the correct version, i.e "v76.tgz".*
    
    # upload using checksum
    FILE="output.tgz"
    UPLOAD_PATH="NSEM/upload/v76.tgz"
    CHECKSUM=$(openssl md5 -binary "${FILE}" | base64)
    aws s3api put-object --bucket cwwed-archives --key "${UPLOAD_PATH}" --body "${FILE}" --metadata md5chksum=${CHECKSUM} --content-md5 ${CHECKSUM} --profile nsem
    
Update the "nsem" record to indicate the post-storm assessment has been uploaded.

    # update the nsem version with the aws s3 path (expects to be named by the version, i.e "v76.tgz")
    curl -s -XPATCH -H "Authorization: Token aca89a70c8fa67144109b368b2b9994241bdbf2c" -H "Content-Type: application/json" -d '{"model_output_snapshot": "NSEM/upload/v76.tgz"}' "http://127.0.0.1:8000/api/nsem/76/"
    
    {
      "id": 76,
      "covered_data_storage_url": "s3://cwwed-archives/NSEM/Harvey/v76/Covered Data",
      "date_requested": "2018-05-09T18:48:47.685854Z",
      "date_returned": null,
      "covered_data_snapshot": "NSEM/Harvey/v58/Covered Data",
      "model_output_snapshot": "NSEM/upload/v58.tgz",
      "model_output_snapshot_extracted": false,
      "named_storm": 1
    }
    
The `model_output_snapshot_extracted` field will initially be `false` until a background job has processed the upload.

## NSEM AWS policies

Create AWS user "nsem" and assign the following polices:

 - `configs/aws/s3-policy-nsem-shared.json` and they'll be able to upload to `s3://cwwed-shared/nsem/`.  See the [wiki instructions](https://github.com/CWWED/cwwed/wiki/NSEM-Shared-Storage-(AWS-S3))
 - `configs/aws/s3-policy-nsem-upload.json` and they'll be able to read everything in `s3://cwwed-archives/NSEM/` and upload to `s3://cwwed-archives/NSEM/upload/`.
