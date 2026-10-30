# x86 plaintext SEND producer design

Status: design only; no DLL injection, game hook or native producer implemented.

## Capture boundary

Use an authorized application integration point immediately before application
encryption, after the complete game packet (including ID and any length) exists.
Winsock send/WSASend may see ciphertext and is not an assumed plaintext boundary.
Before implementing an adapter, determine executable version, calling convention,
argument ownership/lifetime, threading, and whether the call contains one packet,
several packets or a partial packet. Never assume x86 register or stack layouts.

Copy the plaintext into an owned bounded record while the argument is valid.
Record capture time in Unix microseconds, connection generation ID and payload.
Do not modify arguments, return values, order or encryption state. Hook callbacks
must not perform pipe I/O, allocate unbounded memory, or wait for the GUI.

A dedicated worker drains a bounded queue to the local named pipe. On overflow,
record a drop counter; never silently concatenate incomplete records. Connection
IDs are allocated by the producer per application connection generation, never
truncated native pointers. A reconnect creates a new generation ID. Native
integration must report drops out of band until a versioned status record exists.

## GPA1 wire format

All integers are unsigned little endian. No native structs, padding or pointers
are sent. The 20-byte header is followed by exactly one complete game packet:

- Offset 0: 4 bytes ASCII GPA1.
- Offset 4: uint32 raw packet byte count (2..65535).
- Offset 8: uint64 Unix timestamp in microseconds at capture time.
- Offset 16: uint32 connection generation ID.
- Offset 20: raw bytes, starting with the uint16 little endian PacketID.

Python validates exact packet length against PacketLength.txt. A record becomes
PacketEvent(direction='SEND', source='HOOK', connection='hook:<ID>'). Receive
events continue to use NPCAP/RECV. GPA1 intentionally supports SEND only.
Malformed frames close the client connection; no magic-byte resynchronization.
A disconnect discards partial records and a new client gets a fresh decoder.

## Pipe lifecycle

GUI owns the optional server; its generated name is displayed in the GUI.
On Windows the native worker opens `\\.\pipe\<displayed name>` with CreateFileW.
Use byte writes and loop until the entire frame is written, accounting for partial
writes. On a broken pipe discard the partially sent record, close the handle,
back off and reconnect. Do not replay old queued records into a later GUI session.
Stop signals the worker, cancels pending I/O, joins it and frees owned buffers;
never join threads or initialize hooks from DllMain under the loader lock.

QLocalServer restricts access to the same OS user and accepts one active producer.
This is not producer authentication; do not rely on IPC for trusted game identity.
Configure the displayed pipe name explicitly in the producer. Python bitness is
independent of the Win32/x86 adapter. A native test sender must precede actual
game adapter work; verify fragmentation, overflow, disconnect and clean shutdown.

## Native implementation gates

1. Add a Win32 CMake test producer implementing GPA1 with explicit serialization.
2. Verify Windows named pipe interoperability with the GUI and test packet map.
3. Identify and document an authorized plaintext callback and its ABI.
4. Implement the callback adapter, queue and worker; preserve application behavior.
5. Exercise x86 debug/release builds and compare plaintext packet counts/lengths.
