{{- define "mab.fullname" -}}{{ .Release.Name | trunc 40 | trimSuffix "-" }}{{- end -}}

{{- define "mab.labels" -}}
app.kubernetes.io/part-of: mab-platform
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "mab.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "mab.image" -}}
{{- $reg := .root.Values.image.registry -}}
{{- if $reg }}{{ $reg }}/{{ end }}{{ index .root.Values.image .name }}:{{ .root.Values.image.tag }}
{{- end -}}

{{- define "mab.secretName" -}}
{{- if .Values.secrets.existingSecret }}{{ .Values.secrets.existingSecret }}{{ else }}{{ include "mab.fullname" . }}-secrets{{ end -}}
{{- end -}}

{{- define "mab.serviceAccountName" -}}
{{- if .Values.serviceAccount.name }}{{ .Values.serviceAccount.name }}{{ else }}{{ include "mab.fullname" . }}{{ end -}}
{{- end -}}

{{/* Variabel lingkungan bersama: ConfigMap + Secret */}}
{{- define "mab.envFrom" -}}
- configMapRef:
    name: {{ include "mab.fullname" . }}-config
- secretRef:
    name: {{ include "mab.secretName" . }}
{{- end -}}

{{- define "mab.podSecurity" -}}
{{- toYaml .Values.podSecurityContext }}
{{- end -}}

{{- define "mab.containerSecurity" -}}
{{- toYaml .Values.containerSecurityContext }}
{{- end -}}

{{/* Volume data sintetis (LLM mock) bila diaktifkan */}}
{{- define "mab.syntheticMount" -}}
{{- if .Values.syntheticData.enabled }}
- name: synthetic
  mountPath: /app/data/synthetic_output
  readOnly: true
{{- end }}
{{- end -}}
{{- define "mab.syntheticVolume" -}}
{{- if .Values.syntheticData.enabled }}
- name: synthetic
  persistentVolumeClaim:
    claimName: {{ include "mab.fullname" . }}-synthetic
{{- end }}
{{- end -}}
