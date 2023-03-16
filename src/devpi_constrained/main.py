from devpi_common.metadata import parse_requirement, splitext_archive
from devpi_common.types import cached_property
from devpi_common.validation import normalize_name
from pluggy import HookimplMarker
import pkg_resources


server_hookimpl = HookimplMarker("devpiserver")


class ContraintsDict(dict):
    constrain_all = False


def parse_constraints(constraints):
    result = ContraintsDict()
    for constraint in constraints:
        if constraint == '*':
            result.constrain_all = True
            continue
        try:
            constraint = parse_requirement(constraint)
        except pkg_resources.RequirementParseError as e:
            raise pkg_resources.RequirementParseError(
                "%s for %r" % (e, constraint))
        if constraint.project_name in result:
            raise ValueError("Constraint for '%s' already exists." % constraint.project_name)
        result[constraint.project_name] = constraint
    return result


class ConstrainedStage(object):
    readonly = True

    def get_possible_indexconfig_keys(self):
        return ("constraints",)

    def get_default_config_items(self):
        return [("constraints", [])]

    def normalize_indexconfig_value(self, key, value):
        if key == "constraints":
            if not isinstance(value, list):
                result = []
                for item in value.splitlines():
                    item = item.strip()
                    if not item or item.startswith('#'):
                        continue
                    result.append(item)
                return result
            return value

    def validate_config(self, oldconfig, newconfig):
        errors = []
        try:
            parse_constraints(newconfig['constraints'])
        except Exception as e:
            errors.append("Error while parsing constrains: %s" % e)
        if len(newconfig["bases"]) < 1:
            errors.append("A constrained index requires at least one base")
        if errors:
            raise self.InvalidIndexconfig(errors)

    @cached_property
    def constraints(self):
        return parse_constraints(
            self.stage.ixconfig.get("constraints", ""))

    def get_projects_filter_iter(self, projects):
        constraints = self.constraints
        if not constraints.constrain_all:
            return
        for project in projects:
            yield project in constraints

    def get_versions_filter_iter(self, project, versions):
        version_filter = self.constraints.get(project)
        if version_filter is None:
            return
        for version in versions:
            yield version in version_filter

    def get_simple_links_filter_iter(self, project, links):
        constraints = self.constraints
        version_filter = constraints.get(project)
        if version_filter is None:
            return
        for link_info in links:
            if isinstance(link_info, tuple):
                key = link_info[0]
                parts = splitext_archive(key)[0].split('-')
                for index in range(1, len(parts)):
                    name = normalize_name('-'.join(parts[:index]))
                    if name != project:
                        continue
                    version = '-'.join(parts[index:])
                    if version in version_filter:
                        yield True
                        break
                    else:
                        yield False
            else:
                if link_info.name != project:
                    continue
                if link_info.version in version_filter:
                    yield True
                else:
                    yield False


@server_hookimpl
def devpiserver_get_stage_customizer_classes():
    return [("constrained", ConstrainedStage)]
