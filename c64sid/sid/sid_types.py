from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

SidModel = Literal['6581', '8580', 'UNKNOWN']
PlaybackMethod = Literal['VBI_Call', 'CIA_Interrupt']
InterruptType = Literal['IRQ', 'NMI']


@dataclass
class SidHeader:
    magic: Literal['PSID', 'RSID']
    version: int
    dataOffset: int

    loadAddress: int
    initAddress: int
    playAddress: int

    songs: int
    startSong: int
    speed: int

    title: str
    author: str
    released: str

    flags: int
    isNtsc: bool
    clockFreq: int

    model: SidModel
    sidCount: int
    sidModels: List[SidModel]
    sidAddresses: List[int]

    c64BasicFlag: bool


@dataclass
class C64Roms:
    kernal: Optional[bytes] = None
    basic: Optional[bytes] = None
    chargen: Optional[bytes] = None

# Alias for compatibility
RomPack = C64Roms


@dataclass
class C64Config:
    enableHle: bool = True
    roms: C64Roms = field(default_factory=C64Roms)
    busPersistenceCycles: int = 0x1D00
    enableAdsrPipeline: bool = True
    enableCombinedWaveforms: bool = True
    noiseSeed: int = 0x7FFFFF
    exportDepth: Literal['NONE', 'BASIC', 'FULL'] = 'FULL'


@dataclass
class InterruptEvent:
    cycles: int
    type: InterruptType
    source: str
    vectorAddr: int
    handlerAddr: int
