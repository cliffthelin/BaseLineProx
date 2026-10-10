import pytest

import hardware_inventory as inventory


@pytest.mark.parametrize('bus',['pci','block','network'])
def test_required_hardware_bus_rejects_blank_probe_output(bus):
    with pytest.raises(inventory.InventoryError,match='empty output'):
        inventory.require_bus_output(bus,'\n  \n')


def test_usb_inventory_can_be_empty_when_probe_succeeded():
    assert inventory.require_bus_output('usb','\n',allow_empty=True)=='\n'
