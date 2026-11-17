"""The retraining itself. Run by the Python that has the training tools (PyTorch, NeMo),
not by the app: see training.py, which starts it and follows it.

  python -m dictation.trainer --data FOLDER --base parakeet-v2 --name NAME --job FOLDER
                              --models FOLDER [--passes 10] [--resume]
"""
