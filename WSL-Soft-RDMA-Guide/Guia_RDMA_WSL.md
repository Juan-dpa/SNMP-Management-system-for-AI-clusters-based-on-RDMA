# Guía: habilitar Soft-RoCE (RDMA) en WSL2 mediante kernel custom

Esta guía explica cómo compilar un kernel de WSL2 con soporte para Soft-RoCE (RDMA sobre Ethernet) y configurarlo para que WSL lo use. El resultado final es que `rdma link` reporta un dispositivo `rxe0` funcional dentro de WSL.

## 0. Requisitos previos

Antes de empezar, comprueba desde **PowerShell**:

```powershell
wsl --version
```

Necesitas WSL **2.5.1 o superior** para que acepte módulos cargados desde un VHDX. Si tienes una versión anterior:

```powershell
wsl --update
```

Se recomienda tener al menos 8 GB libres en disco, ya que el árbol del kernel y los artefactos de compilación ocupan espacio.

Antes de empezar, como medida de seguridad, haz backup de tu distro WSL actual (desde PowerShell):

```powershell
wsl --export Ubuntu C:\backup\ubuntu-backup.tar
```

Esto te permite restaurar si algo sale mal con `wsl --import`.

## 1. Instalar dependencias de compilación

Dentro de tu terminal WSL (Ubuntu):

```bash
sudo apt update
sudo apt install -y build-essential flex bison libssl-dev libelf-dev \
    libncurses-dev bc python3 pahole cpio kmod rsync git dwarves qemu-utils
```

## 2. Clonar el kernel de Microsoft

Ubícate en tu home y clona la rama 6.18 LTS:

```bash
cd ~
git clone --depth=1 -b linux-msft-wsl-6.18.y \
    https://github.com/microsoft/WSL2-Linux-Kernel.git
cd WSL2-Linux-Kernel
```

**Importante:** compila dentro de `~`, nunca dentro de `/mnt/c/...`, porque la E/S sobre el sistema de archivos de Windows es órdenes de magnitud más lenta.

## 3. Preparar el archivo de configuración

Copia la configuración oficial de Microsoft como base y ábrela con la interfaz de configuración:

```bash
cp Microsoft/config-wsl .config
make menuconfig KCONFIG_CONFIG=.config
```

Se abrirá una interfaz de texto con menús (`menuconfig`).

## 4. Navegar por menuconfig

### Controles básicos

- **Flechas ↑ ↓**: moverse entre opciones de un menú.
- **Flechas ← →**: moverse entre los botones inferiores (`<Select>`, `<Exit>`, `<Help>`).
- **Enter**: entrar en un submenú (las líneas con `--->` al final son submenús).
- **Espacio** o **M**: cambiar el estado de la opción resaltada a módulo (`<M>`).
- **Y**: activar como built-in (`<*>`).
- **N**: desactivar.
- **/**: abrir buscador de opciones.
- **?**: mostrar ayuda y dependencias.
- **Esc Esc**: salir del menú actual (o del programa si ya estás en la raíz).

### Estados visuales

| Símbolo | Significado |
|--|--|
| `[ ]` / `< >` | Desactivado |
| `[*]` | Built-in (compilado dentro del kernel) |
| `<M>` | Módulo cargable (.ko) |
| `<*>` | Tristate marcado como built-in |

Para Soft-RoCE queremos todo en modo **`<M>`** (módulo).

## 5. Activar las opciones necesarias

Desde el menú principal de `menuconfig`, navega a:

```
Device Drivers  --->
  InfiniBand support  --->
```

Si `InfiniBand support` aparece como `< >`, sitúate encima y pulsa `M` para marcarlo como módulo. Entra en el submenú con Enter y marca las siguientes opciones como `<M>`:

- `InfiniBand userspace MAD support`
- `InfiniBand userspace access (verbs and CM)`
- `Software RDMA over Ethernet (RoCE) driver`

Opcional (solo si alguna herramienta vieja lo requiere):

- `[*] Allow experimental legacy verbs API`

Cuando lo tengas, sal pulsando Esc Esc sucesivamente hasta que pregunte si guardar los cambios → **Yes**.

### Verificación rápida

Confirma que las opciones quedaron escritas:

```bash
grep -E "CONFIG_(RDMA_RXE|INFINIBAND|RDMA_CM|RDMA_UCM)=" .config
```

Debes ver cada línea con `=m` o `=y`. Si alguna falta, vuelve a `menuconfig`.

Resuelve posibles dependencias pendientes:

```bash
make olddefconfig KCONFIG_CONFIG=.config
```

A las preguntas que aparezcan responde con Enter para aceptar los valores por defecto.

## 6. Compilar el kernel y los módulos

```bash
make -j$(nproc) KCONFIG_CONFIG=.config
make -j$(nproc) KCONFIG_CONFIG=.config INSTALL_MOD_PATH="$PWD/modules" modules_install
```

El primer comando tarda entre 15 y 40 minutos según el equipo. Al terminar tendrás:

- `arch/x86/boot/bzImage` — el kernel.
- `modules/lib/modules/<version>/` — los módulos (`rdma_rxe.ko`, `ib_core.ko`, etc.).

## 7. Generar el VHDX de módulos

```bash
sudo ./Microsoft/scripts/gen_modules_vhdx.sh \
    "$PWD/modules" \
    "$(make -s kernelrelease)" \
    modules.vhdx
```

Al acabar, verifica:

```bash
ls -lh modules.vhdx
```

## 8. Copiar los artefactos a Windows

Primero, identifica tu nombre de usuario **de Windows** (no el de Linux):

```bash
cmd.exe /c 'echo %USERNAME%'
```

Apunta ese nombre. En los siguientes comandos sustituye `<USUARIO_WINDOWS>` por el valor obtenido:

```bash
mkdir -p /mnt/c/Users/<USUARIO_WINDOWS>/wsl-kernel
cp arch/x86/boot/bzImage /mnt/c/Users/<USUARIO_WINDOWS>/wsl-kernel/bzImage
cp modules.vhdx          /mnt/c/Users/<USUARIO_WINDOWS>/wsl-kernel/modules.vhdx
```

## 9. Configurar `.wslconfig`

Desde la misma terminal WSL, crea el archivo de configuración de WSL (sustituye `<USUARIO_WINDOWS>`):

```bash
cat > /mnt/c/Users/<USUARIO_WINDOWS>/.wslconfig << 'EOF'
[wsl2]
kernel=C:\\Users\\<USUARIO_WINDOWS>\\wsl-kernel\\bzImage
kernelModules=C:\\Users\\<USUARIO_WINDOWS>\\wsl-kernel\\modules.vhdx
EOF
```

**Importante:** edita el archivo a mano después y reemplaza `<USUARIO_WINDOWS>` por tu nombre real. Las barras dobles `\\` son obligatorias: son sintaxis de Windows escapada. Con barras simples WSL no encontrará el archivo.

## 10. Reiniciar WSL

Desde **PowerShell** (no desde WSL):

```powershell
wsl --shutdown
```

Vuelve a abrir tu terminal WSL.

## 11. Verificar que el kernel nuevo arrancó

```bash
uname -r
```

Debe mostrar una versión 6.18 con el sufijo que hayas definido en `CONFIG_LOCALVERSION` (por defecto `-microsoft-standard-WSL2` o similar).

## 12. Cargar el módulo y levantar el dispositivo RDMA

```bash
sudo apt install -y rdma-core iproute2 ibverbs-utils perftest
sudo modprobe rdma_rxe
sudo rdma link add rxe0 type rxe netdev eth0
```

Si tu interfaz de red en WSL no se llama `eth0`, averigua la correcta con `ip -br link` y sustitúyela en el comando anterior.

## 13. Confirmar que RDMA funciona

```bash
rdma link
ibv_devices
```

Deberías ver algo parecido a:

```
device                 node GUID
------              ----------------
rxe0                02155dfffe5e5a1d
```

Si ves el dispositivo `rxe0`, ya tienes Soft-RoCE operativo dentro de WSL.

## Problemas frecuentes

**WSL no arranca después de reiniciar.** Edita `C:\Users\<USUARIO_WINDOWS>\.wslconfig` y comenta las líneas `kernel=` y `kernelModules=` con un `#` delante. Ejecuta `wsl --shutdown` y vuelve a abrir WSL: estarás de vuelta con el kernel oficial. Desde ahí puedes revisar qué falló.

**`make menuconfig` falla por falta de `ncurses`.** Instala `libncurses-dev` y repite.

**`qemu-img: command not found` al generar el VHDX.** Falta `qemu-utils`; instálalo con `sudo apt install qemu-utils`.

**`rdma link add` da "Operation not supported".** El módulo no se cargó. Comprueba `lsmod | grep rdma_rxe` y, si está vacío, revisa que `uname -r` muestra el kernel nuevo y que `modules.vhdx` está bien referenciado en el `.wslconfig`.

**Quiero volver al kernel original.** Borra o comenta las líneas `kernel=` y `kernelModules=` del `.wslconfig` y ejecuta `wsl --shutdown` desde PowerShell.