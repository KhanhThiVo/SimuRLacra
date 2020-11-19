conda deactivate

conda remove -n pyrado --all

cds
git pull

conda create -y -n pyrado python=3.7
conda activate pyrado
conda install -y blas cmake lapack libgcc-ng mkl patchelf pip setuptools -c conda-forge
pip install argparse box2d colorama coverage cython glfw gym joblib prettyprinter matplotlib numpy optuna pandas pycairo pytest pytest-cov pytest-xdist pyyaml scipy seaborn sphinx sphinx-math-dollar sphinx_rtd_theme tabulate tensorboard tqdm vpython git+https://github.com/Xfel/init-args-serializer.git@master

python setup_deps.py w_rcs_w_pytorch -j32 --headless
