import json
import pydot
from os.path import isfile, join
from collections import namedtuple
import logging

Dependence = namedtuple("Dependence", "source to graph full_dep")


class Project:
    def __init__(self, project_codemodel, codemodel):
        self._project_codemodel = project_codemodel
        self._codemodel = codemodel
        self._graph = None
        self._project_node = None

    def name(self):
        return self._project_codemodel["name"]

    def parent_index(self):
        return self._project_codemodel.get("parentIndex")

    def subproj_indexes(self):
        return self._project_codemodel["childIndexes"]

    def target_indexes(self):
        return self._project_codemodel["targetIndexes"]

    def directory_indexes(self):
        return self._project_codemodel["directoryIndexes"]

    def full_dependence(self, target):
        deps = target.dependency_indexes()
        return all(ind in deps for ind in self.target_indexes())

    def get_project_node(self):
        if self._graph is None:
            self._graph = self.get_graph()
        assert self._project_node is not None
        return self._project_node

    def get_graph(self, layout="dot", bgcolor="white", style="dotted"):
        if self._graph is not None:
            return self._graph

        pr_name = self.name()
        dir_sources = []
        for i in self.directory_indexes():
            dir_sources.append(self._codemodel["directories"][i]["source"])

        pr_graph = pydot.Cluster(
            # f"cluster_{pr_name}",
            pr_name,
            label=pr_name,
            tooltip="\n".join(dir_sources),
            bgcolor=bgcolor,
            layout=layout,
            style=style,
        )
        pr_graph.set("class", "project")

        # add a dummy invisible node per cluster
        # in the case we need an edge pointing at the whole project
        # like when all targets of the project are used
        project_node = pydot.Node(
            f"PROJNODE_{pr_graph.get_name()}",
            label=self.name(),
            shape="point",
            style="invis",
        )
        pr_graph.add_node(project_node)
        self._project_node = project_node

        self._graph = pr_graph
        return self._graph


class Directory:
    def __init__(self, directory_codemodel, codemodel, reply_dir):
        self._directory_codemodel = directory_codemodel
        self._codemodel = codemodel
        self._graph = None

        json_fpath = join(reply_dir, directory_codemodel["jsonFile"])
        assert isfile(json_fpath)
        with open(json_fpath, "r") as f:
            self._json = json.load(f)

    def source(self):
        return self._directory_codemodel["source"]

    def subdir_indexes(self):
        return self._directory_codemodel["childIndexes"]

    def target_indexes(self):
        return self._directory_codemodel["targetIndexes"]

    def project_index(self):
        return self._directory_codemodel["projectIndex"]

    def full_dependence(self, target):
        deps = target.dependency_indexes()
        return all(ind in deps for ind in self.target_indexes())

    def get_graph(self, layout="dot"):
        if self._graph is not None:
            return self._graph

        dir_source = self.source()
        dir_graph = pydot.Cluster(
            dir_source,
            label=f"📁 {dir_source}",
            labeljust="l",
            layout=layout,
            style="dotted",
            penwidth=0,
        )
        dir_graph.set("class", "directory")

        self._graph = dir_graph
        return self._graph


class Target:
    def __init__(self, target_codemodel, codemodel, reply_dir):
        json_fpath = join(reply_dir, target_codemodel["jsonFile"])
        assert isfile(json_fpath)
        with open(json_fpath, "r") as f:
            self._json = json.load(f)

        self._target_codemodel = target_codemodel
        self._codemodel = codemodel
        self.project = codemodel["projects"][self.project_index()]
        self.directory = codemodel["directories"][self.directory_index()]
        self._label = self.target_name()
        self._graph = None
        self._marker = None
        self._usage_count = 0
        self._dep_markers = []

    def set_label(self, label):
        self._label = label

        if self._graph is None:
            return

        if self._dep_markers:
            graph_label = label + "\n" + " ".join(self._dep_markers)
        else:
            graph_label = label

        self._graph.set_label(graph_label)

    def add_dep_marker(self, dep_mark):
        self._dep_markers.append(dep_mark)
        self.set_label(self._label)

    def set_marker(self, marker, usage_count):
        self._marker = marker
        self._usage_count = usage_count
        self.set_label(f"@{marker}({usage_count}) {self._label}")

    def get_marker(self):
        return self._marker

    def type(self):
        return self._json["type"]

    def sources(self):
        return [src["path"] for src in self._json.get("sources", [])]

    def compile_groups(self):
        cmp_info = []
        sources = self.sources()
        for cmp in self._json.get("compileGroups", []):
            info = {
                "sources": [sources[i] for i in cmp["sourceIndexes"]],
                "includes": [i["path"] for i in cmp.get("includes", [])],
                "defines": [i["define"] for i in cmp.get("defines", [])],
            }
            cmp_info.append(info)
        return cmp_info

    def cmake_lists(self):
        return self._json["backtraceGraph"]["files"]

    def dependency_ids(self):
        return [dep["id"] for dep in self._json.get("dependencies", [])]

    def dependency_indexes(self):
        inds = []
        dep_ids = self.dependency_ids()
        for i, t_model in enumerate(self._codemodel["targets"]):
            if t_model["id"] in dep_ids:
                inds.append(i)
        return inds

    def target_id(self):
        return self._json["id"]

    def target_name(self):
        return self._json["name"]

    def project_index(self):
        return self._target_codemodel["projectIndex"]

    def directory_index(self):
        return self._target_codemodel["directoryIndex"]

    def target_install_paths(self):
        install = self._json.get("install")
        if install is None:
            return None
        prefix = install["prefix"]["path"]
        destinations = [d for d in install["destinations"]]
        return [join(prefix, d["path"]) for d in destinations]

    def find_cmake_define(self):
        bg = self._json["backtraceGraph"]
        def_commands = ("add_executable", "add_library")
        definitions = [
            (i, com) for i, com in enumerate(bg["commands"]) if com in def_commands
        ]
        if not definitions:
            return None

        assert len(definitions) == 1
        def_index, def_com = definitions[0]

        for node in bg["nodes"]:
            if node.get("command") == def_index:
                def_info = node
                break
        def_file = bg["files"][def_info["file"]]
        def_line = def_info["line"]

        return def_com, def_file, def_line

    def get_graph(self):
        if self._graph is not None:
            return self._graph

        t_name = self.target_name()
        t_type = self.type()

        # create the node and dependencies
        extra_info = []
        extra_info.append(f"type={t_type}")

        definition = self.find_cmake_define()
        if definition:
            com, fname, line = definition
            extra_info.append(f"{com} @ {fname}:{line}")

        extra_info.append(f"len(depends)={len(self.dependency_ids())}")
        dep_defs = []
        for dep_ind in self.dependency_indexes():
            dep_model = self._codemodel["targets"][dep_ind]
            dep_proj_ind = dep_model["projectIndex"]
            dep_proj_name = self._codemodel["projects"][dep_proj_ind]["name"]
            dep_defs.append(f"{dep_proj_name}: {dep_model["name"]}")
        extra_info.append("\n".join(["deps:"] + sorted(dep_defs)))

        installs = self.target_install_paths()
        if installs:
            extra_info.append(f"installs:\n{'\n'.join(installs)}")

        compile_groups = self.compile_groups()
        if compile_groups:
            extra_info.append("compile_groups:")
        for cmp in compile_groups:
            extra_info.append("\n".join(["includes:"] + cmp["includes"]))
            extra_info.append("\n".join(["defines:"] + cmp["defines"]))
            extra_info.append("\n".join(["sources:"] + cmp["sources"]))

        target_node = pydot.Node(
            t_name, label=self._label, tooltip="\n".join(extra_info)
        )
        target_node.set("class", "node")

        self._graph = target_node
        self.set_label(self._label)
        return self._graph


class Codemodel:
    def __init__(self, codemodel_dir, cfg, perproject=True):
        self.name = cfg["name"]

        self.root_graph = pydot.Dot(
            f"targetgraph-{self.name}",
            graph_type="digraph",
            bgcolor="white",
            compound=True,
        )

        self.projects = []
        for pr in cfg["projects"]:
            self.projects.append(Project(pr, cfg))

        self.directories = []
        for dir_model in cfg["directories"]:
            directory = Directory(dir_model, cfg, codemodel_dir)
            self.directories.append(directory)

        self.targets = []
        for t_model in cfg["targets"]:
            target = Target(
                target_codemodel=t_model,
                codemodel=cfg,
                reply_dir=codemodel_dir,
            )
            self.targets.append(target)

        # collect target-target dependencies
        self.dependencies = []
        for target in self.targets:
            project = self.projects[target.project_index()]

            full_project_dependencies = set()
            for dep_ind in target.dependency_indexes():
                # if dependencies include all targets of a project
                # then depend on the whole project
                # - add lhead=cluester name
                dep_target = self.targets[dep_ind]
                dep_proj = self.projects[dep_target.project_index()]
                dep_proj_id = dep_proj.get_graph().get_name()

                full_dep = dep_proj.full_dependence(target)

                edge_style = (
                    "invis" if dep_proj_id in full_project_dependencies else "dashed"
                )
                logging.debug(
                    f"check full deps: {target.target_name()} {dep_proj_id} in {full_project_dependencies}"
                )

                dep_name = dep_target.target_name()
                if (
                    perproject
                    and full_dep
                    and target.project_index() != dep_target.project_index()
                ):
                    dep_name = dep_proj.get_project_node().get_name()
                    # dep_proj_name = dep_proj.get_project_node().get_label()
                    # edge_tooltip = f"all targets from\n{dep_proj_name}"

                if target.project_index() == dep_target.project_index():
                    # project.get_graph().add_edge(dep_edge)
                    graph_for_edge = project.get_graph()
                else:
                    # graph.add_edge(dep_edge)
                    graph_for_edge = self.root_graph

                dep = Dependence(
                    target,
                    dep_target,
                    graph=graph_for_edge,
                    full_dep=(perproject and full_dep),
                )
                self.dependencies.append(dep)

                logging.debug(
                    f"Added node dep: {target.target_name()} {dep_name} : {target.dependency_indexes()} - {dep_proj.target_indexes()}"
                )

        pass
