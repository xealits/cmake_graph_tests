plots:
	cmake_graph graph -B tryouts/cmake_template/build --skip-types UTILITY --skip-names test_ --frequent-deps-threshold 3
	cmake_graph graph -B temp/cmake/build --skip-types UTILITY --frequent-deps-threshold 3
	mv targetgraph-.svg targetgraph-_cmake.svg
	cmake_graph graph -B temp/rocksdb//build --skip-types UTILITY --skip-names "rocksdb_check|.*test.*" --frequent-deps-threshold 3
	cmake_graph graph -B temp/abseil-cpp/build --skip-types UTILITY --frequent-deps-threshold 3
	mv targetgraph-.svg targetgraph-_abseil.svg

copy:
	cp targetgraph-Release.svg examples/targetgraph-Release_cmake_template.svg
	cp targetgraph-_cmake.svg examples/targetgraph-_cmake.svg
	cp targetgraph-Debug.svg examples/targetgraph-Debug_rocksdb_notests.svg
	cp targetgraph-_abseil.svg examples/targetgraph-_abseil.svg

rebuild:
	python -m build
	#pip uninstall -y cmake_graph_tests
	#pip install dist/*whl

install:
	pip install --editable .
