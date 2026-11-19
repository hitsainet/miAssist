"""The detector-probe playbook (miAssist 003): five goal tools (``tools.DETECTOR_SPECS``, added by
``miassist.tools.all_specs``), a status provider (``status.PROVIDER``, registered in Core's
``PROVIDERS``) and the definition ``playbooks/definitions/detector-probe.json``. This package
initialiser imports nothing, so ``adapters.routes`` can import its route table without a cycle."""
