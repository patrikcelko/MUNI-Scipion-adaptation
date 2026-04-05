{{- define "scipion3-remote.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "scipion3-remote.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "scipion3-remote.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}

{{- define "scipion3-remote.labels" -}}
app.kubernetes.io/name: {{ include "scipion3-remote.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ include "scipion3-remote.chart" . }}
{{- end -}}

{{- define "scipion3-remote.selectorLabels" -}}
app.kubernetes.io/name: {{ include "scipion3-remote.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
