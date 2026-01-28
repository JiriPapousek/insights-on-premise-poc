#!/bin/bash
oc apply -f deploy/namespace.yml
#oc apply -f deploy/search-postgres-network-policy.yml
oc get secret search-postgres -n open-cluster-management -o json | \
  jq 'del(.metadata.namespace, .metadata.uid, .metadata.resourceVersion, .metadata.creationTimestamp, .metadata.ownerReferences) | .metadata.namespace = "insights-on-prem-poc"' | \
  oc apply --namespace insights-on-prem-poc -f -
oc apply -f deploy/quay-secret.yml --namespace insights-on-prem-poc
oc apply -f deploy/insights.yml --namespace insights-on-prem-poc
oc apply -f deploy/service.yml --namespace insights-on-prem-poc

# Update insights-client deployment to use the on-premise service
oc set env deployment/insights-client -n open-cluster-management \
  CCX_SERVER=http://insights-on-prem.insights-on-prem-poc.svc.cluster.local:8000