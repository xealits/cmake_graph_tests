python -m build
pip uninstall -y cmake_graph_tests
pip install dist/*whl
