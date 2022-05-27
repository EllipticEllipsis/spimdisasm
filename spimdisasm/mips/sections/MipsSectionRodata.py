#!/usr/bin/env python3

# SPDX-FileCopyrightText: © 2022 Decompollaborate
# SPDX-License-Identifier: MIT

from __future__ import annotations

from ... import common

from .. import symbols

from . import SectionBase


class SectionRodata(SectionBase):
    def __init__(self, context: common.Context, vram: int|None, filename: str, array_of_bytes: bytearray):
        super().__init__(context, vram, filename, array_of_bytes, common.FileSectionType.Rodata)

        self.bytes: bytearray = bytearray(self.sizew*4)
        common.Utils.beWordsToBytes(self.words, self.bytes)

        # addresses of symbols in this rodata section
        self.symbolsVRams: set[int] = set()


    def _stringGuesser(self, contextSym: common.ContextSymbolBase, localOffset: int) -> bool:
        if contextSym.isMaybeString or contextSym.isString():
            return True

        if not common.GlobalConfig.STRING_GUESSER:
            return False

        if not contextSym.hasNoType() or contextSym.referenceCounter > 1:
            return False

        # This would mean the string is an empty string, which is not very likely
        if self.bytes[localOffset] == 0:
            return False

        try:
            common.Utils.decodeString(self.bytes, localOffset)
        except (UnicodeDecodeError, RuntimeError):
            # String can't be decoded
            return False
        return True

    def _processElfRelocSymbols(self) -> None:
        if len(self.context.relocSymbols[self.sectionType]) == 0:
            return

        # Process reloc symbols (probably from a .elf file)
        inFileOffset = self.inFileOffset
        for w in self.words:
            relocSymbol = self.context.getRelocSymbol(inFileOffset, self.sectionType)
            if relocSymbol is not None:
                if relocSymbol.name.startswith("."):
                    sectType = common.FileSectionType.fromStr(relocSymbol.name)
                    relocSymbol.sectionType = sectType

                    relocName = f"{relocSymbol.name}_{w:06X}"
                    contextOffsetSym = common.ContextOffsetSymbol(w, relocName, sectType)
                    if sectType == common.FileSectionType.Text:
                        # jumptable
                        relocName = f"L{w:06X}"
                        contextOffsetSym = self.context.addOffsetJumpTableLabel(w, relocName, common.FileSectionType.Text)
                        relocSymbol.type = contextOffsetSym.type
                        offsetSym = self.context.getOffsetSymbol(inFileOffset, self.sectionType)
                        if offsetSym is not None:
                            offsetSym.type = common.SymbolSpecialType.jumptable
                    self.context.offsetSymbols[sectType][w] = contextOffsetSym
                    relocSymbol.name = relocName
                    # print(relocSymbol.name, f"{w:X}")
            inFileOffset += 4

    def analyze(self):
        self.checkAndCreateFirstSymbol()

        symbolList = []
        localOffset = 0

        partOfJumpTable = False
        for w in self.words:
            currentVram = self.getVramOffset(localOffset)
            contextSym = self.context.getSymbol(currentVram, tryPlusOffset=False)

            if contextSym is not None and contextSym.isJumpTable():
                partOfJumpTable = True

            elif partOfJumpTable:
                if localOffset in self.pointersOffsets:
                    partOfJumpTable = True

                elif self.context.getSymbol(currentVram) is not None:
                    partOfJumpTable = False

                elif ((w >> 24) & 0xFF) != 0x80:
                    partOfJumpTable = False

            if partOfJumpTable:
                labelSym = self.context.addJumpTableLabel(w, isAutogenerated=True)
                labelSym.referenceCounter += 1

            elif currentVram in self.context.newPointersInData:
                if common.GlobalConfig.ADD_NEW_SYMBOLS:
                    contextSym = self.context.getSymbol(currentVram, tryPlusOffset=False)
                    if contextSym is None:
                        contextSym = self.context.addSymbol(currentVram, None, self.sectionType, isAutogenerated=True)
                        contextSym.isDefined = True

                    contextSym.isMaybeString = self._stringGuesser(contextSym, localOffset)
                    self.context.newPointersInData.remove(currentVram)

            elif contextSym is not None:
                contextSym.isMaybeString = self._stringGuesser(contextSym, localOffset)

            contextSym = self.context.getSymbol(currentVram, tryPlusOffset=False)
            if contextSym is not None:
                self.symbolsVRams.add(currentVram)
                contextSym.isDefined = True

                symbolList.append((localOffset, currentVram, contextSym.name))

            localOffset += 4

        for i, (offset, vram, symName) in enumerate(symbolList):
            if i + 1 == len(symbolList):
                words = self.words[offset//4:]
            else:
                nextOffset = symbolList[i+1][0]
                words = self.words[offset//4:nextOffset//4]

            symVram = None
            if self.vram is not None:
                symVram = vram

            sym = symbols.SymbolRodata(self.context, offset + self.inFileOffset, symVram, symName, words)
            sym.setCommentOffset(self.commentOffset)
            sym.analyze()
            self.symbolList.append(sym)

        self._processElfRelocSymbols()


    def removePointers(self) -> bool:
        if not common.GlobalConfig.REMOVE_POINTERS:
            return False

        was_updated = super().removePointers()
        for i in range(self.sizew):
            top_byte = (self.words[i] >> 24) & 0xFF
            if top_byte == 0x80:
                self.words[i] = top_byte << 24
                was_updated = True
            if (top_byte & 0xF0) == 0x00 and (top_byte & 0x0F) != 0x00:
                self.words[i] = top_byte << 24
                was_updated = True

        return was_updated
