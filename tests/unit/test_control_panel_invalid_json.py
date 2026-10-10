import http.client
import threading

import control_panel_web as cpw
from physical_device_safety import Runner as PhysicalDeviceRunner
from repair import RealRunner


def test_control_panel_rejects_malformed_json_before_dispatch(tmp_path):
    server=cpw.make_server(runner=RealRunner(),pds_runner=PhysicalDeviceRunner(),
        config_path=str(tmp_path/'control-config.json'),host='127.0.0.1',port=0)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        conn=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
        conn.request('POST','/api/backup','{malformed',{'Content-Type':'application/json'})
        response=conn.getresponse();body=response.read()
        assert response.status==400 and b'malformed JSON' in body
        conn.close()
    finally:
        server.shutdown();server.server_close();worker.join(timeout=5)
