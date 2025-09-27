plots:
	cmake_graph graph -B tryouts/cmake_template/build --skip-types UTILITY --skip-names test_ --frequent-deps-threshold 3
	cmake_graph graph -B temp/cmake/build --skip-types UTILITY --frequent-deps-threshold 3

copy:
	cp targetgraph-Release.svg examples/targetgraph-Release_cmake_template.svg
	cp targetgraph-.svg examples/targetgraph-_cmake.svg

rebuild:
	python -m build
	#pip uninstall -y cmake_graph_tests
	#pip install dist/*whl

install:
	pip install --editable .
