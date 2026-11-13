# Linux
Grunderna i terminalen och hur man tar hand om en Linux-dator eller server: kommandon, rättigheter, tjänster, uppdateringar, nätverk, loggar och backup.

## Att komma igång
Linux är själva **kärnan** i operativsystemet. En **distribution** som Ubuntu eller Debian paketerar kärnan med program och verktyg. Du skriver kommandon i en **terminal**, och ett **skal** (oftast bash) tolkar dem.
Prompten visar vem du är, på vilken dator och i vilken katalog: `anna@server:~$`. Tecknet `~` betyder din hemkatalog. Slutar prompten på `$` är du en vanlig användare, och på `#` är du root.
| Genväg | Gör |
|---|---|
| Tab | fyller i resten av kommandot eller filnamnet |
| Ctrl+C | avbryter programmet som körs |
| Pil upp | tidigare kommando |
| Ctrl+R | söker bland tidigare kommandon |
| Ctrl+L | rensar skärmen |
| `man ls` | manualsidan för ls (lämna med q) |
| `ls --help` | kort hjälp för ett kommando |
> Det finns ingen papperskorg i terminalen. Det som du raderar med `rm` är borta, så läs kommandot en extra gång innan du trycker Enter.

## Navigera och hantera filer
| Kommando | Gör | Exempel |
|---|---|---|
| pwd | visar katalogen du står i | `pwd` |
| ls | listar filer | `ls -lah` (långt format, dolda filer, läsbara storlekar) |
| cd | byter katalog | `cd /var/log`, `cd ..` (upp), `cd ~` (hem), `cd -` (förra) |
| mkdir | skapar en katalog | `mkdir -p a/b/c` (hela kedjan) |
| touch | skapar en tom fil | `touch anteckningar.txt` |
| cp | kopierar | `cp fil.txt kopia.txt`, `cp -r mapp mapp2` |
| mv | flyttar eller döper om | `mv gammal.txt ny.txt` |
| rm | raderar | `rm fil.txt`, `rm -r mapp` |
| ln -s | skapar en symbolisk länk (genväg) | `ln -s /var/log/nginx loggar` |
| find | letar efter filer | `find /home -name "*.txt"` |
Filer som börjar med en punkt, som `.bashrc`, är **dolda** och syns bara med `ls -a`.

## Läsa och söka i text
| Kommando | Gör |
|---|---|
| `cat fil` | skriver ut hela filen |
| `less fil` | bläddra i en lång fil (q avslutar, / söker) |
| `head -n 20 fil` | de 20 första raderna |
| `tail -n 20 fil` | de 20 sista raderna |
| `tail -f fil` | följer filen och visar nya rader när de kommer |
| `grep ord fil` | rader som innehåller ordet (`-i` struntar i stora och små bokstäver, `-r` söker i en hel katalog) |
| `wc -l fil` | antal rader |
| `nano fil` | enkel textredigerare (Ctrl+O sparar, Ctrl+X avslutar) |
### Pipes och omdirigering
- `kommando1 | kommando2` skickar utdata från det första som indata till det andra, till exempel `ps aux | grep nginx`
- `>` skriver utdata till en fil och ersätter det som fanns i den
- `>>` lägger till sist i filen
- `2>&1` skickar felmeddelanden dit vanlig utdata går, till exempel `jobb > logg.txt 2>&1`
- `sort | uniq -c` räknar hur många gånger varje rad förekommer (sortera alltid först)
- `kommando &` kör kommandot i bakgrunden

## Rättigheter och användare
Varje fil har en **ägare**, en **grupp** och rättigheter för **ägare, grupp och övriga**. I `ls -l` ser du till exempel `-rwxr-xr--`: första tecknet är typen (`-` fil, `d` katalog, `l` länk), sedan kommer tre tecken var för ägare, grupp och övriga.
| Bokstav | Siffra | Betyder |
|---|---|---|
| r | 4 | läsa |
| w | 2 | skriva |
| x | 1 | köra (för kataloger: gå in i den) |
Siffrorna adderas: 7 = 4+2+1 (allt), 6 = 4+2, 5 = 4+1, 4 = bara läsa.
| Läge | Visas som | Används till |
|---|---|---|
| 644 | rw-r--r-- | vanliga filer |
| 755 | rwxr-xr-x | program, skript och kataloger |
| 600 | rw------- | privata filer, till exempel en privat SSH-nyckel |
| 700 | rwx------ | privata kataloger, till exempel ~/.ssh |
| 777 | rwxrwxrwx | undvik, alla får göra allt |
- `chmod 755 fil` ändrar rättigheterna, och `chmod +x skript.sh` gör filen körbar
- `chown anna:anna fil` ändrar ägare och grupp (kräver oftast sudo)
- `sudo kommando` kör kommandot som administratör (root), och `sudo !!` kör det senaste kommandot igen med sudo
- `whoami` visar ditt användarnamn, och `sudo adduser anna` skapar en ny användare
- `sudo usermod -aG sudo anna` ger anna sudo-rättigheter (`-a` är viktigt, annars försvinner hon ur andra grupper)
- sudo-reglerna ändras med `sudo visudo`, som kontrollerar filen innan den sparas
> **setuid** (till exempel 4755) gör att ett program körs med ägarens rättigheter. Det behövs för vissa systemprogram men är riskabelt.

## Processer och tjänster
| Kommando | Gör |
|---|---|
| `ps aux` | listar alla processer just nu |
| `top` eller `htop` | processer och resursanvändning live (q avslutar) |
| `kill 1234` | ber process 1234 avsluta sig snällt |
| `kill -9 1234` | dödar processen direkt, utan städning (sista utväg) |
| `uptime` | tid sedan start och **load average** (belastning för 1, 5 och 15 minuter) |
| `free -h` | minne (RAM) och swap |
Load average runt antalet CPU-kärnor betyder att datorn är fullt utnyttjad. Över det köar processerna.
### systemd
Tjänster (webbserver, databas, SSH) styrs med `systemctl`:
| Kommando | Gör |
|---|---|
| `systemctl status nginx` | visar om tjänsten körs, och de senaste loggraderna |
| `sudo systemctl start nginx` | startar tjänsten nu |
| `sudo systemctl stop nginx` | stoppar tjänsten |
| `sudo systemctl restart nginx` | stoppar och startar igen |
| `sudo systemctl reload nginx` | läser om inställningarna utan att stoppa |
| `sudo systemctl enable nginx` | startar tjänsten automatiskt vid uppstart |
| `sudo systemctl enable --now nginx` | gör både enable och start |
| `systemctl --failed` | visar tjänster som har misslyckats |
| `sudo systemctl daemon-reload` | läser om .service-filer som du ändrat |
### Cron: jobb enligt schema
`crontab -e` redigerar dina schemalagda jobb, och `crontab -l` visar dem. Varje rad har fem tidsfält följt av kommandot:
| Fält | Värden |
|---|---|
| Minut | 0–59 |
| Timme | 0–23 |
| Dag i månaden | 1–31 |
| Månad | 1–12 |
| Veckodag | 0–7 (0 och 7 är söndag) |
| Schema | Betyder |
|---|---|
| `30 3 * * *` | varje dag klockan 03:30 |
| `*/5 * * * *` | var femte minut |
| `0 4 * * 1` | måndagar klockan 04:00 |
| `0 0 1 * *` | den första varje månad, vid midnatt |
> Cron har en minimal miljö och en kort **PATH**. Skriv hela sökvägar (`/usr/bin/docker`) och skicka utdata till en logg, till exempel `>> /tmp/jobb.log 2>&1`, så ser du vad som gick fel.

## Paket och uppdateringar
Ubuntu och Debian använder **apt**. Kör alltid `update` först, för det hämtar bara listan över vad som finns.
| Kommando | Gör |
|---|---|
| `sudo apt update` | hämtar de senaste paketlistorna |
| `sudo apt upgrade` | installerar nyare versioner av det som redan är installerat |
| `sudo apt install htop` | installerar ett paket (`-y` svarar ja på frågorna) |
| `sudo apt remove htop` | avinstallerar ett paket |
| `sudo apt autoremove` | tar bort beroenden som inte längre behövs |
| `sudo reboot` | startar om datorn |
Finns filen `/var/run/reboot-required` behöver datorn startas om, till exempel efter en kärnuppdatering. Paketet **unattended-upgrades** installerar säkerhetsuppdateringar automatiskt.

## Nätverk och SSH
| Kommando | Gör |
|---|---|
| `ip a` | visar IP-adresser och nätverkskort |
| `ip r` | visar routingtabellen (bland annat gatewayen) |
| `ping 8.8.8.8` | testar om en dator svarar |
| `curl https://example.com` | hämtar en webbsida eller ett API-svar (`-I` visar bara svarshuvudena) |
| `sudo ss -tlnp` | visar lyssnande TCP-portar och vilket program som använder dem |
| `sudo lsof -i :8080` | visar vilken process som använder port 8080 |
| Port | Används till |
|---|---|
| 22 | SSH |
| 80 | HTTP |
| 443 | HTTPS |
| 53 | DNS |
| 3306 | MariaDB och MySQL |
| 5432 | PostgreSQL |
### SSH
- `ssh anna@192.168.1.10` loggar in på en annan dator (`-p 2222` om den lyssnar på en annan port)
- `scp fil anna@192.168.1.10:/tmp/` kopierar en fil via SSH
- `ssh-keygen -t ed25519` skapar ett nyckelpar: den **privata** nyckeln behåller du (rättigheter 600), den **publika** (.pub) lägger du på servern
- `ssh-copy-id anna@192.168.1.10` lägger din publika nyckel i `~/.ssh/authorized_keys` på servern
- I `/etc/ssh/sshd_config` stänger `PasswordAuthentication no` av lösenordsinloggning och `PermitRootLogin no` av root-inloggning. Testa nyckeln först och starta om tjänsten med `sudo systemctl restart ssh`.
### Brandvägg
| Kommando | Gör |
|---|---|
| `sudo ufw allow 22/tcp` | tillåter inkommande SSH (gör det före enable) |
| `sudo ufw enable` | slår på brandväggen |
| `sudo ufw status numbered` | visar reglerna med nummer |
| `sudo ufw delete 2` | tar bort regel 2 |
**fail2ban** läser loggar och blockerar tillfälligt IP-adresser som gång på gång misslyckas med att logga in.

## Diskar, loggar och backup
| Kommando | Gör |
|---|---|
| `df -h` | ledigt utrymme per filsystem |
| `df -i` | antal lediga **inoder** (slut på inoder ger "No space left" trots ledigt utrymme) |
| `du -sh /var/log` | hur mycket en katalog tar |
| `lsblk` | diskar och partitioner som ett träd |
| `sudo dmesg` | kärnans meddelanden, till exempel hårdvarufel och OOM-händelser |
Filsystem som monteras vid uppstart står i `/etc/fstab`. Testa ändringar med `sudo mount -a` innan du startar om.
### Loggar
- Loggfilerna ligger i `/var/log`, och `tail -f /var/log/syslog` följer dem live
- `journalctl -u nginx` visar journalen för en tjänst, `-f` följer den och `-n 50` visar de 50 senaste raderna
- **logrotate** roterar, packar och tar bort gamla loggar så att de inte fyller disken
### Backup
- `tar -czf backup.tar.gz mapp` packar en katalog, och `tar -xzf backup.tar.gz` packar upp den
- `rsync -av källa/ användare@dator:mål/` kopierar bara det som ändrats, och `--delete` speglar även raderingar (prova med `--dry-run` först)
- **3-2-1-regeln:** 3 kopior, på 2 sorters lagring, varav 1 på en annan plats
- Testa att du kan **återställa** en backup. Först då vet du att den fungerar.

## Docker
| Kommando | Gör |
|---|---|
| `docker ps` | containrar som körs (`-a` visar även stoppade) |
| `docker logs -f --tail 50 web` | följer de senaste 50 loggraderna från containern web |
| `docker exec -it web sh` | öppnar ett skal inne i en container som körs |
| `docker compose up -d` | startar tjänsterna i docker-compose.yml i bakgrunden |
| `docker compose down` | stoppar och tar bort containrarna (volymerna ligger kvar) |
| `docker compose pull` | hämtar nya images (kör sedan `up -d` för att starta om dem) |
| `docker system prune` | tar bort stoppade containrar, oanvända nätverk och namnlösa images |
Det en container skriver försvinner när containern tas bort, om du inte har monterat en **volym** eller en katalog (till exempel `./data:/data`). Allt som ska finnas kvar, som databaser och uppladdade filer, hör hemma där.

## Viktiga kataloger
| Katalog | Innehåll |
|---|---|
| / | roten, allt ligger under den |
| /home | användarnas hemkataloger |
| /root | root-användarens hemkatalog |
| /etc | inställningar för system och tjänster |
| /var/log | loggfiler |
| /tmp | tillfälliga filer |
| /usr/bin | de flesta program |
| /dev | enheter, till exempel diskar |
| /proc | information om processer och kärnan |

## Felsökning och säkerhet
1. Läs **felmeddelandet** noga, det säger oftast vad som är fel
2. Kolla **statusen**: `systemctl status tjänst`, sedan `journalctl -u tjänst` och loggarna i `/var/log`
3. Kolla **resurserna**: `df -h`, `df -i`, `free -h` och `top`
4. Kolla **nätverket**: `ip a`, `ping`, `sudo ss -tlnp` och brandväggen
5. Ändra **en sak i taget** och testa efter varje ändring
`echo $?` visar slutkoden från det senaste kommandot: 0 betyder att det gick bra, allt annat betyder fel. I ett bash-skript gör `set -e` att skriptet avbryts så fort ett kommando misslyckas.
> Ge inte program fler rättigheter än de behöver. `chmod -R 777` löser sällan det verkliga problemet och öppnar för alla. Kör inte heller saker som root i onödan.
