import json
import os

class JupyterFormBuilder():
    SHELL_FILE = os.path.join("html", "form_shell.html")

    def __init__(self):
        try:
            self.form_html_content = self._build_form_template()
        except Exception as e:
            self.form_html_content = f"FORM_TEMPLATE_ERROR: {e}"

    def _resource_root(self):
        return os.path.join(os.path.dirname(__file__), "resources")

    def _read_resource(self, relative_path):
        resource_path = os.path.join(self._resource_root(), relative_path)
        with open(resource_path, "r", encoding="utf-8") as file:
            return file.read()

    def _discover_resources(self, subdirectory, extension):
        discovered_resources = []
        root_directory = os.path.join(self._resource_root(), subdirectory)

        for current_root, _, filenames in os.walk(root_directory):
            for filename in filenames:
                if not filename.endswith(extension):
                    continue

                resource_path = os.path.join(current_root, filename)
                relative_path = os.path.relpath(resource_path, self._resource_root())
                discovered_resources.append(relative_path)

        return tuple(sorted(discovered_resources))

    def _build_form_template(self):
        shell_html = self._read_resource(self.SHELL_FILE)
        bundled_css = "\n\n".join(
            self._read_resource(path)
            for path in self._discover_resources("css", ".css")
        )
        bundled_js = "\n\n".join(
            self._read_resource(path)
            for path in self._discover_resources("js", ".js")
        )

        return (
            shell_html
            .replace("<!-- INLINE_CSS -->", f"<style>\n{bundled_css}\n</style>")
            .replace("<!-- INLINE_JS -->", f"<script>\n{bundled_js}\n</script>")
        )

    def _safe_fetch(self, formdata, key, default):
        return formdata[key][0] if key in formdata else default

    def _parse_bool(self, value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        normalized_value = str(value).strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off", ""}:
            return False
        return default
    
    def get_html_page(self, dicitonaryList, nodeHealthSnapshots=None, uiContext=None, nodeHealthHistory=None):
        payload = {
            "machines": dicitonaryList,
            "nodeHealth": nodeHealthSnapshots or {},
            "uiContext": uiContext or {},
            "nodeHealthHistory": nodeHealthHistory or {},
        }
        jsonPayload = json.dumps(payload).replace("</", "<\\/")
        return self.form_html_content.replace("{formPayload}", jsonPayload)

    def get_form_options(self, formdata):
        options = {}
        options['machineSelect'] = int(self._safe_fetch(formdata, 'machineSelect', 0))
        shared_access_value = self._safe_fetch(
            formdata,
            'sharedAccessValue',
            self._safe_fetch(formdata, 'sharedAccess', True),
        )
        options['sharedAccess'] = self._parse_bool(shared_access_value, True)
        machine_instance_id = self._safe_fetch(formdata, 'machineInstanceId', None)
        options['machineInstanceId'] = machine_instance_id if machine_instance_id else None
        ssh_gateway_password = self._safe_fetch(formdata, 'sshGatewayPassword', None)
        options['sshGatewayPassword'] = ssh_gateway_password if ssh_gateway_password else None
        return options
