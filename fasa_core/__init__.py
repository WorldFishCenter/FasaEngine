"""FASA feed formulation engine — core package.

Public entry point:
    >>> from fasa_core.optimizer import formulate
    >>> result = formulate(species="Nile Tilapia",
    ...                    stage="< 5g (Starter)",
    ...                    production_system="General-LowCost",
    ...                    prices={"30355": 0.30, "31237": 0.55, ...},
    ...                    processing_method="pelleted")
"""

__version__ = "0.1.0"
