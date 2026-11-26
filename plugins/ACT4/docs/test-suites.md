
# 可选 Test Suite 目标

两个生成工作流的运行配置 `suite`必须使用下表
**Test Suite** 列中代码格式的命令行目标（CLI target），大小写精确匹配。
原名与命令行目标不同时，在同一单元格换行补充原名。`xiangshan-v3-handoff` 仍按香山模块选择，不受此列表限制。
这些目标来自 [ACT 进度表的 Test Suite 列](https://docs.google.com/spreadsheets/d/1EuG4LV1TQDx4wTzYDWEAvq0fwaWjNuxenwDARZmrN-E/edit?gid=0#gid=0)。

- 普通名称保持原样，如 `I`、`Sstc`、`Vx32`、`IOMMU`；复杂名称的空格和标点转换为表中明确列出的安全标识，
  例如 `Sspm (Smnpm*)` 对应 `Sspm_Smnpm`。标识不是原生文件名；实际规范和资产入口由工作流解析。
- 同名记录合并为一个目标，但保留全部来源行。`Sstc` 与供应方条目 `sstc` 是不同目标，不能自动转换大小写。
  组合条目仍是完整请求，不能只选择其中已经实现的部分；分组标题和没有具体范围的提醒不作为目标。
- 启动时先校验目标，再准备资源和环境；不存在的目标立即报错，并尽可能提示相近名称。
  终端显示原名、说明、来源行、分组、负责人和表中资产状态。Review 的独立 ISA 计划不使用这些进度状态设计测试。
- 校验使用插件内置快照，不需要联网，也不把每次运行绑定到在线表格。表格新增目标后需更新插件目录快照，
  方法见 [开发说明](development.md#test-suite-目录)。状态是快照信息，不代表本次已生成、验证通过或覆盖完整。
- 列表只限定请求范围，不是“现有资产齐全”的白名单。缺计划、规则映射、生成器或免费工具仍是工作流的补全任务。
  两个生成入口按测试机制选择，不能仅凭目标在列表内就断言它适合无 trap 的指令生成。

<!-- ACT4-SUITES:START -->

Snapshot: **2026-11-19**. **267** CLI targets / **291** nonempty Test Suite cells.

| Test Suite | Description |
| --- | --- |
| `I` | Integer |
| `M` | Mult/Divide |
| `Zaamo` | Atomic Memory Ops |
| `Zalrsc` | Load Reserved |
| `Zca` | Compressed |
| `Zcf` | Compressed Float |
| `Zcd` | Compressed Double |
| `F` | Float |
| `D` | Double |
| `Zifencei` | Instruction Fence |
| `Zicntr` | Counters |
| `Zihpm` | Performance Monitors |
| `ZicsrF` | Float CSRs |
| `Misalign` | Misaligned Load/Store |
| `Zicsr` | CSR write/set/clear |
| `Sm` | Machine CSRs & Inst |
| `Exceptions` | Exceptions |
| `Interrupts` | Interrupts |
| `PMP` | Physical Memory Protection |
| `Zba` | Address Calculation |
| `Zbb` | Bit Manipulation |
| `Zbs` | Single-Bit Ops |
| `Zfhmin` | Half-Precision Convert |
| `Zihintpause` | Pause Hint |
| `Zicbom` | Cache Ops |
| `Zicboz` | Cache Zero |
| `Zicbop` | Cache Prefetch |
| `Zicclsm` | Misaligned Loads/Stores |
| `Za64rs` | 64B Reservation Sets |
| `Zic64b` | 64B Cache zeros |
| `Ziccif` | Instruction Fetch PMA |
| `Ziccrse` | RsrvEventual PMA |
| `Ziccamoa` | Atomic PMA |
| `Ziccamoc` | AMOCASQ PMA |
| `S` | Supervisor CSRs & Inst |
| `U` | User CSRs & Inst |
| `Sstc` | Supervisor Timer Interrupts |
| `Svbare` | No VirtMem |
| `Sv` | VirtMem |
| `Svinval` | VM Invalidation |
| `Svade` | VM A/D Exception |
| `Svpbmt` | VM Page Memory Type |
| `Sscounterenw` | Counter Enables |
| `Sstvecd` | Vectored Interrupts |
| `Ssccptr` | Hardware page table reads |
| `Sstvala` | stval address |
| `Zfh` | Half FP |
| `Zbc` | Carryless Mult |
| `Zbkb` | Crypto Bit Manipulation |
| `Zbkc` | Crypto Carryless Mult |
| `Zbkx` | Permutations |
| `Zknd` | AES Decrypt |
| `Zkne` | AES Encrypt |
| `Zknh` | SHA2 Hash |
| `Zksed` | SM4 Cipher |
| `Zksh` | SM3 Hash |
| `Ssstrict` | Reserved Exceptions |
| `Zkr` | Entropy CSR |
| `Zcb` | Additional Compressed |
| `Zfa` | Additional FP |
| `Zicond` | Conditional |
| `Zihintntl` | Locality Hints |
| `Zimop` | Maybe-Ops |
| `Zcmop` | Compressed Maybe-Ops |
| `Zawrs` | Wait on Reservation Set |
| `Svnapot` | NAPOT VM |
| `Sscofpmf` | Counter Filtering |
| `Ssnpm` | User Pointer Masking |
| `Ssu64xl` | 64b User Mode |
| `Svadu` | Hardware A/D Update |
| `Sspm_Smnpm`<br>Sspm (Smnpm*) | Supervisor Pointer Masking |
| `Svvptc` | Valid PTEs Visible |
| `SdtrigS_SdtrigU_SdtrigH`<br>SdtrigS, SdtrigU, SdtrigH | Debug Triggers |
| `Multimaster_Fences_RVWMO_TSO`<br>Multimaster Fences / RVWMO / TSO | Not specified in sheet |
| `Multimaster_Atomics_Zaamo_Zalrsc_Zawrs_Zabha_Zacas`<br>Multimaster Atomics (Zaamo, Zalrsc, Zawrs, Zabha, Zacas) | Not specified in sheet |
| `Vx8` | Vector Integer |
| `Vx16` | Vector Integer |
| `Vx32` | Vector Integer |
| `Vx64` | Vector Integer |
| `Vls8` | Vector Load/Store |
| `Vls16` | Vector Load/Store |
| `Vls32` | Vector Load/Store |
| `Vls64` | Vector Load/Store |
| `Vf32` | Vector Float |
| `Vf64` | Vector Float |
| `Zvbb8` | Vector Bit Manipulation |
| `Zvbb16` | Vector Bit Manipulation |
| `Zvbb32` | Vector Bit Manipulation |
| `Zvbb64` | Vector Bit Manipulation |
| `ExceptionsVx` | Vector Int Exceptions |
| `ExceptionsVf` | Vector Float Exceptions |
| `ExceptionsVls` | Vector LS Exceptions |
| `MisalignV` | Vector Misaligned |
| `SsstrictV` | Vector Strict Exceptions |
| `Ssstateen` | Supervisor State Enable |
| `Vf16_Zvfh`<br>Vf16 (Zvfh) | Vector Half Float (Zvfh) |
| `Zvkb8` | Vector Crypto Bit |
| `Zvkb16` | Vector Crypto Bit |
| `Zvkb32` | Vector Crypto Bit |
| `Zvkb64` | Vector Crypto Bit |
| `Zvbc64` | Vector Carryless Mult |
| `Zvkg` | Vector GCM |
| `Zvkned` | Vector AES Crypto |
| `Zvknh` | Vector SHA2 Hash |
| `Zvksed` | Vector Shangmi Crypto |
| `Zvksh` | Vector SM4 Hash |
| `Zvfhmin` | Vector Half Convert |
| `Zvfbfmin` | Vector BrainFloat Convert |
| `Zvfbfwma` | Vector Brainfloat FWMA |
| `Zacas` | Atomic CompareAndSwap |
| `Zabha` | Subword Atomics |
| `Zama16b` | Misaligned Atomics |
| `Zicfilp` | Landing Pad |
| `Zicfiss` | Shadow Stack |
| `Zfbfmin` | Brain Float Convert |
| `H` | Hypervisor CSR/Instr; Hypervisor CSRs & Inst |
| `Shcounterenw` | Hypervisor counter enable; Supervisor Counter En |
| `Shtvala` | Hypervisor htval written; htval address |
| `Shvstvala` | Hypervisor vstval written; vstval address |
| `Shgatpa` | Hypervisor hgatp modes; hgatp address |
| `Shvsatpa` | Hypervisor vsatp modes; vsatp address |
| `Shvstvecd` | Hypervisor vstvec modes; vstvec address |
| `Svpbmt_henvcfg_PBMT_is_0_if_menvcfg_PBMT_0`<br>Svpbmt: henvcfg.PBMT is 0 if menvcfg.PBMT=0 | Not specified in sheet |
| `Svadu_henvcfg_ADUE_0_if_menvcfg_henvcfg_ADUE_writable_hw_update_of_G_stage_PTE`<br>Svadu: henvcfg.ADUE = 0 if menvcfg..., henvcfg.ADUE writable, hw update of G-stage PTE | Not specified in sheet |
| `Svnapot_in_G_stage`<br>Svnapot in G-stage | Not specified in sheet |
| `Svrsw60t59b_on_G_stage`<br>Svrsw60t59b on G-stage | Not specified in sheet |
| `Ssdbltrp_henvcfg_DTE_vssstatus_SDT`<br>Ssdbltrp: henvcfg.DTE, vssstatus.SDT | Not specified in sheet |
| `Zicfiss_HLV_HSV`<br>Zicfiss: HLV/HSV* | Not specified in sheet |
| `Zicbo_mtinst_htinst_transformation`<br>Zicbo: mtinst/htinst transformation | Not specified in sheet |
| `Zawrs_VTW`<br>Zawrs: VTW | Not specified in sheet |
| `Zkr_test_SSEED_and_VSSEED_from_VS_VU`<br>Zkr: test SSEED and VSSEED from VS/VU | Not specified in sheet |
| `SdtrigH` | Move into merged Sdtrig |
| `SmcntrpmfH` | check if this is right |
| `Smcsrind_Sscsrind_later`<br>Smcsrind/Sscsrind later | Not specified in sheet |
| `Smcdeleg_Ssccfg_later`<br>Smcdeleg/Ssccfg later | Not specified in sheet |
| `Smctr_later`<br>Smctr later | Not specified in sheet |
| `Ssqosid_later`<br>Ssqosid later | Not specified in sheet |
| `ExceptionsH` | Hypervisor Exceptions |
| `ExceptionsHV` | Hyper-Vector Exceptions |
| `InterruptsH` | Hypervisor Interrupts |
| `ZicntrH` | Hypervisor Counters |
| `PMPH` | Hypervisor PMP |
| `SvH` | Hypervisor VirtMem |
| `SvinvalH` | Hypervisor Svinval |
| `SvHCBO` | Hypervisor VM CBO |
| `Shlcofideleg` | Hypervisor counter overflow; Hypervisor LCOFI Delegation |
| `ZkrH` | Hypervisor Entropy CSR |
| `SstcH` | Hypervisor Timer |
| `SsnpmH` | Hypervisor Pointer Masking |
| `SsstateenH` | Hypervisor State Enable |
| `ZicfilpH` | Hypervisor Landing Pad |
| `ZicfissH` | Hypervisor Shadow Stack |
| `SvaduH` | Hypervisor A/D Update |
| `Zcmp` | Compressed Push/Pop |
| `Zcmt` | Compressed Jump Table |
| `ExceptionsZicboSm` | Machine CBO Exceptions |
| `EndianSm` | Machine Endian |
| `EndianS` | Supervisor Endian |
| `EndianU` | User Endian |
| `EndianZaamo` | AMO Endian |
| `EndianZalrsc` | LRSC Endian |
| `EndianF` | Float Endian |
| `EndianZc` | Compressed Endian |
| `EndianH` | Hypervisor Endian |
| `E` | Embedded 16 Registers |
| `DM` | Debug Module |
| `DTM` | Debug Transfer Module |
| `Sdext` | External Debug |
| `Smaia` | Machine Advanced Interrupts |
| `Ssaia` | Supervisor Advanced Interrupts |
| `IMSIC` | MSI Controller |
| `APLIC` | Platform Interrupt Controller |
| `IOMMU` | I/O Memory Management |
| `Q` | Quad FP |
| `ZfhQ` | Half-Quad |
| `ZfhminQ` | Half-Quad Converts |
| `ZfaQ` | Additional Quads |
| `ZfaZfhQ` | Additional Converts |
| `MisalignQ` | Misaligned Quad Load/Store |
| `Svrsw60t59b` | Reserved Software Bits |
| `Zmmul` | Multiply |
| `Smmpm` | Pointer Masking |
| `Zfinx` | Float in Int Registers |
| `Zdinx` | Double in Int Regs |
| `Zhinx` | Half in Int Regs |
| `Zhinxmin` | Half Cvt in Int Regs |
| `Zilsd` | Load/Store Double |
| `Zclsd` | Compressed Load/Store Double |
| `Zalasr` | Atomic Load-Acquire/Store-Release |
| `PMPV` | PMP on Vector |
| `Smstateen` | Machine State Enable |
| `Smcsrind` | Machine CSR Indirect |
| `Sscsrind` | Supervisor CSR Indirect |
| `SscrindH` | Hypervisor CSR Indirect |
| `Smepmp` | Enhanced PMP |
| `Smrnmi` | Machine NMI |
| `Ssrnmi` | Supervisor NMI |
| `Smcntrpmf` | Counter Filtering |
| `Smcdeleg` | Counter Delegation |
| `Ssccfg` | Supervisor Counter Delegation |
| `SscfgH` | Hypervisor Counter Delegation |
| `Smdbltrp` | Machine Double Trap |
| `Ssdbltrp` | Supervisor Double Trap |
| `SsdbltrpH` | Hypervisor Double Trap |
| `Smctr` | Control Transfer Records |
| `SmctrH` | Hypervisor CTR |
| `Ssqosid` | Quality of Service |
| `IBM_FP_Coverpoints`<br>IBM FP Coverpoints | Not specified in sheet |
| `Memory_map_addresses_above_32_bits_address_0_illegal_address_starting_addresses_other_than_0x8000_0000_tiny_memory_microcontrollers`<br>Memory map: addresses above 32 bits, address 0 / illegal address, starting addresses other than 0x8000_0000, tiny memory microcontrollers | Not specified in sheet |
| `PMAs_Phase_1B`<br>PMAs (Phase 1B) | Not specified in sheet |
| `Basic_Pipeline_Hazards`<br>Basic Pipeline Hazards | Not specified in sheet |
| `Zkt` | Constant Time |
| `Zvkt` | Constant Time Vector |
| `XlenS_U_VS_VU`<br>XlenS/U/VS/VU | Configurable XLEN |
| `PMAs`<br>PMAs (?) | Not specified in sheet |
| `hypervisor` | Not specified in sheet |
| `hypervisor_exceptions` | Not specified in sheet |
| `hypervisor_interrupts` | Not specified in sheet |
| `hypervisor_paging` | Not specified in sheet |
| `hypervisor_tlb_fence` | Not specified in sheet |
| `sstc` | includes vstimecmp |
| `smstateen_ssstaten` | includes hstateen |
| `sscofpmf` | enables for VS and VU mode overflow (missing) |
| `zicbom` | some cases provide virtualized=True |
| `ssu64xl` | some cases provide virtualized=True |
| `zawrs` | some cases provide virtualized=True |
| `zicntr` | some cases provide virtualized=True |
| `Hypervisor_CSR` | H |
| `Hypervisor_Exceptions` | Exceptions_Hypervisor |
| `Hypervisor_Interrupts` | Interrupts_Hypervisor |
| `Hypervisor_Smnpm` | Smnpm_Hypervisor |
| `Hypervisor_Ssccptr` | Not specified in sheet |
| `Hypervisor_Ssnpm` | Not specified in sheet |
| `Hypervisor_Ssstateen` | Not specified in sheet |
| `Hypervisor_Sstc` | Not specified in sheet |
| `Hypervisor_Sstvala` | Not specified in sheet |
| `Hypervisor_Sscofpmf` | Not specified in sheet |
| `Hypervisor_Svadu` | Not specified in sheet |
| `Hypervisor_Svinval` | Not specified in sheet |
| `Hypervisor_Svnapot` | Not specified in sheet |
| `Hypervisor_Svpbmt` | Not specified in sheet |
| `Hypervisor_Zicbom` | Not specified in sheet |
| `Hypervisor_Zicbop` | Not specified in sheet |
| `Hypervisor_Zicboz` | Not specified in sheet |
| `Hypervisor_Zicfilp` | Not specified in sheet |
| `Hypervisor_Zicfiss` | Not specified in sheet |
| `Hypervisor_Zkr` | Not specified in sheet |
| `Sha` | Not specified in sheet |
| `Hypervisor_Zaamo` | Not specified in sheet |
| `Hypervisor_Zabha` | Not specified in sheet |
| `Hypervisor_Zacas` | Not specified in sheet |
| `Hypervisor_Zalrsc` | Not specified in sheet |
| `Hypervisor_Zawrs` | Not specified in sheet |
| `Hypervisor_Zicntr` | Not specified in sheet |
| `Hypervisor_Zihintntl` | Not specified in sheet |
| `Hypervisor_Zihpm` | Not specified in sheet |
| `Hypervisor_Vector` | Not specified in sheet |
| `Hypervisor_Zca` | Not specified in sheet |
| `Hypervisor_Sdtrig` | Not specified in sheet |
| `Hypervisor_Smcntrpmf` | Not specified in sheet |
| `Hypervisor_Sscsrind` | Not specified in sheet |
| `Hypervisor_Smmpm` | Not specified in sheet |
| `Hypervisor_Smstateen` | Not specified in sheet |
| `Hypervisor_Ssccfg` | Not specified in sheet |
| `Hypervisor_Ssdbltrp` | Not specified in sheet |
| `Hypervisor_Ssqosid` | Not specified in sheet |
| `Hypervisor_PMP` | Not specified in sheet |

Non-target labels (headings or unspecified scope):

| Test Suite cell | Reason |
| --- | --- |
| Hypervisor Branch | Section heading; choose a specific suite listed beneath it |
| otheres needing attention | Unspecified reminder, without an identifiable test scope |
| Alibaba | Vendor label, without a specific test scope |
| Tenstorrent Hypervisor Suites | Section heading; choose a specific suite listed beneath it |
| Alibaba Hypervisor Suites | Section heading; choose a specific suite listed beneath it |

<!-- ACT4-SUITES:END -->
