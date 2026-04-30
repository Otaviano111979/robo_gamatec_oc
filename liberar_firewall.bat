@echo off
echo Liberando porta 5000 no Firewall do Windows...
netsh advfirewall firewall add rule name="GAMATEC Flask 5000" dir=in action=allow protocol=TCP localport=5000
echo Pronto! Porta 5000 liberada.
pause
