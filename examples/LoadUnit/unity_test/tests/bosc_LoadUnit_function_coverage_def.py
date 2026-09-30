#coding=utf-8

import toffee.funcov as fc


# 功能覆盖组名称需要与功能分析文档中的 <FG-*> 标签严格一致
FG_NAMES = (
    "FG-API",
    "FG-SCALAR-PIPELINE",
    "FG-ARBITRATION",
    "FG-REPLAY-KILL",
    "FG-FORWARD-VIOLATION",
    "FG-EXCEPTION-CONTROL",
    "FG-VECTOR-LOAD",
    "FG-MMIO-LOAD",
    "FG-NONCACHEABLE-LOAD",
    "FG-MISALIGN-LOAD",
    "FG-PREFETCH",
    "FG-WRITEBACK-DATA",
)


# 覆盖率采样的少量跨拍状态缓存，仅用于需要“保持/序列”语义的检查点
_COVERAGE_STATE = {}


def _state(dut):
    return _COVERAGE_STATE.setdefault(
        id(dut),
        {
            "sample_count": 0,
            "seen_reset_high": False,
            "scalar_hold_fields": None,
            "scalar_backpressured": False,
            "ldout_hold_fields": None,
            "vector_hold_fields": None,
            "dcache_miss_pending": False,
            "bank_conflict_pending": False,
            "bank_conflict_lq_idx": 0,
            "sq_forward_pending": False,
            "sbuffer_forward_pending": False,
            "nc_raw_notready_pending": False,
            "nc_writeback_pending": False,
            "nc_path_enter_pending": False,
            "nc_forward_pending": False,
            "nc_clean_writeback_pending": False,
            "wb_dcache_pending": False,
            "wb_forward_pending": False,
            "wb_uncache_pending": False,
        },
    )


def _sig(dut, name):
    return int(getattr(dut, name).value)


def _high(dut, name):
    return _sig(dut, name) == 1


def _any_high(dut, *names):
    return any(_high(dut, name) for name in names)


def _capture_fields(dut, names):
    return tuple(_sig(dut, name) for name in names)


def _check_multi_cycle_step(dut):
    state = _state(dut)
    state["sample_count"] += 1
    return state["sample_count"] >= 2


def _check_reset_sequence(dut):
    state = _state(dut)
    if _high(dut, "reset"):
        state["seen_reset_high"] = True
    return state["seen_reset_high"] and not _any_high(
        dut,
        "io_ldout_valid",
        "io_vecldout_valid",
        "io_wakeup_valid",
        "io_feedback_slow_valid",
        "io_rollback_valid",
    )


def _check_scalar_backpressure_hold(dut):
    state = _state(dut)
    field_names = (
        "io_ldin_bits_uop_robIdx_value",
        "io_ldin_bits_uop_lqIdx_value",
        "io_ldin_bits_src_0",
        "io_ldin_bits_uop_fuOpType",
    )
    if _high(dut, "io_ldin_valid") and not _high(dut, "io_ldin_ready"):
        fields = _capture_fields(dut, field_names)
        if state["scalar_hold_fields"] is None:
            state["scalar_hold_fields"] = fields
            return False
        stable = state["scalar_hold_fields"] == fields
        state["scalar_hold_fields"] = fields
        return stable
    state["scalar_hold_fields"] = None
    return False


def _is_high_conf_prefetch(dut):
    return _high(dut, "io_prefetch_req_valid") and _sig(dut, "io_prefetch_req_bits_confidence") > 0


def _is_low_conf_prefetch(dut):
    return _high(dut, "io_prefetch_req_valid") and _sig(dut, "io_prefetch_req_bits_confidence") == 0


def _ordinary_replay_valid(dut):
    return _high(dut, "io_replay_valid") and not _high(dut, "io_replay_bits_forward_tlDchannel")


def _forward_data_present(dut):
    return any(_sig(dut, f"io_lsq_forward_forwardData_{idx}") != 0 for idx in range(16))


def _sbuffer_forward_data_present(dut):
    return any(_sig(dut, f"io_sbuffer_forwardData_{idx}") != 0 for idx in range(16))


def _ubuffer_forward_data_present(dut):
    return any(_sig(dut, f"io_ubuffer_forwardData_{idx}") != 0 for idx in range(16))


def _any_scalar_exception(dut):
    return _any_high(
        dut,
        "io_ldout_bits_uop_exceptionVec_3",
        "io_ldout_bits_uop_exceptionVec_4",
        "io_ldout_bits_uop_exceptionVec_5",
        "io_ldout_bits_uop_exceptionVec_13",
        "io_ldout_bits_uop_exceptionVec_19",
        "io_ldout_bits_uop_exceptionVec_21",
    )


def _any_vector_exception(dut):
    return _high(dut, "io_vecldout_bits_hasException") or _any_high(
        dut,
        "io_vecldout_bits_exceptionVec_3",
        "io_vecldout_bits_exceptionVec_4",
        "io_vecldout_bits_exceptionVec_5",
        "io_vecldout_bits_exceptionVec_13",
        "io_vecldout_bits_exceptionVec_19",
        "io_vecldout_bits_exceptionVec_21",
    )


def _any_output_exception(dut):
    return _any_scalar_exception(dut) or _any_vector_exception(dut) or _high(dut, "io_wakeup_bits_hasException")


def _visible_cancel_or_rollback(dut):
    return _any_high(
        dut,
        "io_ldCancel_ld2Cancel",
        "io_rollback_valid",
        "io_lsq_ldld_nuke_query_revoke",
        "io_lsq_stld_nuke_query_revoke",
    )


def _count_address_exceptions(dut):
    names = (
        "io_tlb_resp_bits_excp_0_pf_ld",
        "io_tlb_resp_bits_excp_0_gpf_ld",
        "io_tlb_resp_bits_excp_0_af_ld",
        "io_pmp_ld",
        "io_pmp_st",
    )
    return sum(1 for name in names if _high(dut, name))


def _check_replay_invalid_no_stall(dut):
    return (
        not _high(dut, "io_replay_valid")
        and (_high(dut, "io_ldin_valid") or _high(dut, "io_vecldin_valid"))
        and (_high(dut, "io_ldin_ready") or _high(dut, "io_vecldin_ready"))
    )


def _check_uncache_over_lower_requests(dut):
    return (
        _high(dut, "io_lsq_uncache_valid")
        and _high(dut, "io_lsq_uncache_ready")
        and (
            _ordinary_replay_valid(dut)
            or _high(dut, "io_vecldin_valid")
            or _high(dut, "io_ldin_valid")
        )
    )


def _check_nc_over_vector_scalar(dut):
    return (
        _high(dut, "io_lsq_nc_ldin_valid")
        and _high(dut, "io_lsq_nc_ldin_ready")
        and (_high(dut, "io_vecldin_valid") or _high(dut, "io_ldin_valid"))
        and not (_high(dut, "io_vecldin_ready") or _high(dut, "io_ldin_ready"))
    )


def _check_forward_not_ready_replay(dut):
    return (
        (_high(dut, "io_lsq_forward_dataInvalid") or _high(dut, "io_lsq_forward_dataInvalidSqIdx_flag"))
        and (_high(dut, "io_feedback_slow_valid") or _visible_cancel_or_rollback(dut))
        and not _high(dut, "io_ldout_valid")
    )


def _check_forward_addr_mismatch_control(dut):
    return (
        (_high(dut, "io_lsq_forward_addrInvalid") or _high(dut, "io_lsq_forward_addrInvalidSqIdx_flag"))
        and _visible_cancel_or_rollback(dut)
    )


def _check_sq_forward_data_success(dut):
    state = _state(dut)
    if (
        _high(dut, "io_lsq_forward_valid")
        and _forward_data_present(dut)
        and not _high(dut, "io_lsq_forward_dataInvalid")
        and not _high(dut, "io_lsq_forward_addrInvalid")
    ):
        state["sq_forward_pending"] = True
    if state["sq_forward_pending"] and _high(dut, "io_ldout_valid"):
        state["sq_forward_pending"] = False
        return True
    return False


def _check_sbuffer_forward_data_success(dut):
    state = _state(dut)
    if (
        _high(dut, "io_sbuffer_valid")
        and _sbuffer_forward_data_present(dut)
        and not _high(dut, "io_lsq_forward_dataInvalid")
        and not _high(dut, "io_lsq_forward_addrInvalid")
    ):
        state["sbuffer_forward_pending"] = True
    if state["sbuffer_forward_pending"] and _high(dut, "io_ldout_valid"):
        state["sbuffer_forward_pending"] = False
        return True
    return False


def _check_nc_raw_notready_replay(dut):
    state = _state(dut)
    if (
        state["nc_writeback_pending"]
        and
        _high(dut, "io_lsq_stld_nuke_query_req_valid")
        and not _high(dut, "io_lsq_stld_nuke_query_req_ready")
    ):
        state["nc_raw_notready_pending"] = True
    if state["nc_raw_notready_pending"] and (
        _high(dut, "io_feedback_slow_valid") or _visible_cancel_or_rollback(dut)
    ):
        state["nc_raw_notready_pending"] = False
        return True
    return False


def _check_nc_writeback_data(dut):
    state = _state(dut)
    if _high(dut, "io_lsq_nc_ldin_valid"):
        state["nc_writeback_pending"] = True
    if state["nc_writeback_pending"] and _high(dut, "io_ldout_valid") and _sig(dut, "io_ldout_bits_data") != 0:
        state["nc_writeback_pending"] = False
        return True
    return False


def _check_nc_path_enter(dut):
    state = _state(dut)
    if _high(dut, "io_lsq_nc_ldin_valid"):
        state["nc_path_enter_pending"] = True
    if state["nc_path_enter_pending"] and (
        _high(dut, "io_ubuffer_valid")
        or _high(dut, "io_lsq_ldld_nuke_query_req_bits_is_nc")
        or _high(dut, "io_lsq_ldin_bits_nc_with_data")
    ):
        state["nc_path_enter_pending"] = False
        return True
    return False


def _check_nc_forward_success(dut):
    state = _state(dut)
    if _high(dut, "io_lsq_nc_ldin_valid"):
        state["nc_forward_pending"] = True
    if state["nc_forward_pending"] and (
        _ubuffer_forward_data_present(dut) or _forward_data_present(dut)
    ):
        state["nc_forward_pending"] = "waiting_writeback"
    if state["nc_forward_pending"] == "waiting_writeback" and _high(dut, "io_ldout_valid"):
        state["nc_forward_pending"] = False
        return _sig(dut, "io_ldout_bits_data") != 0
    return False


def _check_nc_no_spurious_redirect(dut):
    state = _state(dut)
    if _high(dut, "io_lsq_nc_ldin_valid"):
        state["nc_clean_writeback_pending"] = True
    if state["nc_clean_writeback_pending"] and _high(dut, "io_ldout_valid"):
        state["nc_clean_writeback_pending"] = False
        return not _visible_cancel_or_rollback(dut)
    return False


def _check_writeback_dcache_source(dut):
    state = _state(dut)
    if (
        _sig(dut, "io_dcache_resp_bits_data") != 0
        and not _forward_data_present(dut)
        and not _sbuffer_forward_data_present(dut)
        and not _high(dut, "io_lsq_uncache_valid")
        and not _high(dut, "io_lsq_nc_ldin_valid")
    ):
        state["wb_dcache_pending"] = True
    if state["wb_dcache_pending"] and _high(dut, "io_ldout_valid"):
        state["wb_dcache_pending"] = False
        return not _high(dut, "io_ldout_bits_debug_isMMIO") and not _high(dut, "io_ldout_bits_debug_isNCIO")
    return False


def _check_writeback_forward_source(dut):
    state = _state(dut)
    if _forward_data_present(dut) or _sbuffer_forward_data_present(dut):
        state["wb_forward_pending"] = True
    if state["wb_forward_pending"] and _high(dut, "io_ldout_valid"):
        state["wb_forward_pending"] = False
        return not _high(dut, "io_ldout_bits_debug_isMMIO") and not _high(dut, "io_ldout_bits_debug_isNCIO")
    return False


def _check_writeback_uncache_data_path(dut):
    state = _state(dut)
    if _high(dut, "io_lsq_uncache_valid") or _high(dut, "io_lsq_nc_ldin_valid"):
        state["wb_uncache_pending"] = True
    if state["wb_uncache_pending"] and _high(dut, "io_ldout_valid"):
        state["wb_uncache_pending"] = False
        return (
            _high(dut, "io_ldout_bits_debug_isMMIO")
            or _high(dut, "io_ldout_bits_debug_isNCIO")
        ) and _sig(dut, "io_ldout_bits_data") != 0
    return False


def _check_single_exception(dut):
    return _high(dut, "io_tlb_resp_valid") and _count_address_exceptions(dut) == 1 and _any_output_exception(dut)


def _check_multi_exception_priority(dut):
    return _high(dut, "io_tlb_resp_valid") and _count_address_exceptions(dut) >= 2 and _any_output_exception(dut)


def _check_fast_feedback_proxy(dut):
    # The generated DUT wrapper does not expose io_feedback_fast/fast_uop.
    # Use the earliest visible control response as a proxy for the fast path.
    return (_high(dut, "io_wakeup_valid") or _high(dut, "io_s2_ptr_chasing")) and not _high(
        dut, "io_feedback_slow_valid"
    )


def _check_l2l_fast_forward_proxy(dut):
    # The top-level wrapper does not expose io_l2l_fwd_in/out, so the visible
    # stage-2 pointer-chasing flag and final writeback are used as proxies.
    required = ("io_l2l_fwd_in_valid", "io_l2l_fwd_in_data", "io_l2l_fwd_in_dly_ld_err")
    if not all(hasattr(dut, name) for name in required):
        return False
    return _high(dut, "io_s2_ptr_chasing") and _high(dut, "io_ldout_valid") and not _any_scalar_exception(dut)


def _check_l2l_fast_forward_fail_proxy(dut):
    required = ("io_l2l_fwd_in_valid", "io_ld_fast_match", "io_ld_fast_fuOpType", "io_ld_fast_imm")
    if not all(hasattr(dut, name) for name in required):
        return False
    return _high(dut, "io_s2_ptr_chasing") and _any_high(
        dut,
        "io_dcache_s1_kill",
        "io_dcache_s2_kill",
        "io_ldCancel_ld2Cancel",
        "io_rollback_valid",
    )


def _check_miss_to_replay(dut):
    state = _state(dut)
    if _high(dut, "io_dcache_resp_bits_miss"):
        state["dcache_miss_pending"] = True
    if state["dcache_miss_pending"] and not _high(dut, "io_ldout_valid") and (
        _high(dut, "io_feedback_slow_valid") or _high(dut, "io_fast_rep_out_valid")
    ):
        state["dcache_miss_pending"] = False
        return True
    return False


def _check_bank_conflict_replay_cause_preserved(dut):
    state = _state(dut)
    if _high(dut, "io_dcache_s2_bank_conflict"):
        state["bank_conflict_pending"] = True
        state["bank_conflict_lq_idx"] = _sig(dut, "io_dcache_req_bits_lqIdx_value")
    if state["bank_conflict_pending"] and _high(dut, "io_fast_rep_out_valid"):
        hit = _sig(dut, "io_fast_rep_out_bits_uop_lqIdx_value") == state["bank_conflict_lq_idx"]
        if hit:
            state["bank_conflict_pending"] = False
        return hit
    return False


def _check_l2l_fail_kill_proxy(dut):
    required = ("io_l2l_fwd_in_valid", "io_ld_fast_match", "io_ld_fast_fuOpType", "io_ld_fast_imm")
    if not all(hasattr(dut, name) for name in required):
        return False
    return _high(dut, "io_s2_ptr_chasing") and _any_high(
        dut,
        "io_dcache_s1_kill",
        "io_dcache_s2_kill",
        "io_ldCancel_ld2Cancel",
    )


def _check_l2l_success_no_kill_proxy(dut):
    required = ("io_l2l_fwd_in_valid", "io_l2l_fwd_in_data", "io_l2l_fwd_in_dly_ld_err")
    if not all(hasattr(dut, name) for name in required):
        return False
    return _high(dut, "io_s2_ptr_chasing") and not _any_high(dut, "io_dcache_s1_kill", "io_dcache_s2_kill") and (
        _high(dut, "io_ldout_valid") or _high(dut, "io_wakeup_valid")
    )


def _is_scalar_misaligned(dut):
    return _high(dut, "io_ldin_valid") and (_sig(dut, "io_ldin_bits_src_0") & 0xF) != 0


def _check_misalign_detect_and_enqueue(dut):
    state = _state(dut)
    if _is_scalar_misaligned(dut):
        state["misalign_detect_pending"] = True
    if state.get("misalign_detect_pending", False) and _high(dut, "io_misalign_enq_req_valid"):
        state["misalign_detect_pending"] = False
        return True
    return False


def _misalign_replay_cause_seen(dut):
    return any(_high(dut, f"io_misalign_ldout_bits_rep_info_cause_{idx}") for idx in range(11))


def _check_misalign_split_success(dut, final_split: bool):
    state = _state(dut)
    split_name = "second" if final_split else "first"
    request_seen = _high(dut, "io_misalign_ldin_valid") and (
        _high(dut, "io_misalign_ldin_bits_isFinalSplit") == bool(final_split)
    )
    if request_seen:
        state[f"misalign_{split_name}_split_success_pending"] = True
        state[f"misalign_{split_name}_split_replay_pending"] = True
    pending_key = f"misalign_{split_name}_split_success_pending"
    peer_key = f"misalign_{split_name}_split_replay_pending"
    if state.get(pending_key, False) and _high(dut, "io_misalign_ldout_valid"):
        hit = not _misalign_replay_cause_seen(dut)
        state[pending_key] = False
        if hit:
            state[peer_key] = False
        return hit
    return False


def _check_misalign_split_replay(dut, final_split: bool):
    state = _state(dut)
    split_name = "second" if final_split else "first"
    request_seen = _high(dut, "io_misalign_ldin_valid") and (
        _high(dut, "io_misalign_ldin_bits_isFinalSplit") == bool(final_split)
    )
    if request_seen:
        state[f"misalign_{split_name}_split_success_pending"] = True
        state[f"misalign_{split_name}_split_replay_pending"] = True
    pending_key = f"misalign_{split_name}_split_replay_pending"
    peer_key = f"misalign_{split_name}_split_success_pending"
    if state.get(pending_key, False) and _high(dut, "io_misalign_ldout_valid"):
        hit = _misalign_replay_cause_seen(dut)
        state[pending_key] = False
        if hit:
            state[peer_key] = False
        return hit
    return False


def _check_misalign_wakeup_when_needed(dut):
    state = _state(dut)
    if _high(dut, "io_misalign_ldin_valid") and _high(dut, "io_misalign_ldin_bits_misalignNeedWakeUp"):
        state["misalign_wakeup_pending"] = True
    if state.get("misalign_wakeup_pending", False) and (
        _high(dut, "io_wakeup_valid") or _high(dut, "io_misalign_ldout_valid")
    ):
        state["misalign_wakeup_pending"] = False
        return True
    return False


def _check_misalign_replay_when_not_woken(dut):
    state = _state(dut)
    if _high(dut, "io_misalign_ldin_valid") and not _high(dut, "io_misalign_ldin_bits_misalignNeedWakeUp"):
        state["misalign_replay_pending"] = True
    if state.get("misalign_replay_pending", False) and _high(dut, "io_misalign_ldout_valid"):
        state["misalign_replay_pending"] = False
        return _misalign_replay_cause_seen(dut)
    return False


def _is_nc_misaligned(dut):
    return _high(dut, "io_lsq_nc_ldin_valid") and (_sig(dut, "io_lsq_nc_ldin_bits_paddr") & 0xF) != 0


def _check_scalar_stall_resume(dut):
    state = _state(dut)
    if _high(dut, "io_ldin_valid") and not _high(dut, "io_ldin_ready"):
        state["scalar_backpressured"] = True
        return False
    if state["scalar_backpressured"] and _high(dut, "io_ldin_valid") and _high(dut, "io_ldin_ready"):
        state["scalar_backpressured"] = False
        return True
    return False


def _check_ldout_backpressure_hold(dut):
    state = _state(dut)
    field_names = (
        "io_ldout_bits_data",
        "io_ldout_bits_uop_robIdx_value",
        "io_ldout_bits_uop_lqIdx_value",
    )
    if _high(dut, "io_ldout_valid") and not _high(dut, "io_ldout_ready"):
        fields = _capture_fields(dut, field_names)
        if state["ldout_hold_fields"] is None:
            state["ldout_hold_fields"] = fields
            return False
        stable = state["ldout_hold_fields"] == fields
        state["ldout_hold_fields"] = fields
        return stable
    state["ldout_hold_fields"] = None
    return False


def _check_ldout_release_on_ready(dut):
    state = _state(dut)
    waiting_release = state["ldout_hold_fields"] is not None
    released = waiting_release and _high(dut, "io_ldout_valid") and _high(dut, "io_ldout_ready")
    if released:
        state["ldout_hold_fields"] = None
    return released


def _check_vector_backpressure_hold(dut):
    state = _state(dut)
    field_names = (
        "io_vecldin_bits_mask",
        "io_vecldin_bits_reg_offset",
        "io_vecldin_bits_elemIdx",
        "io_vecldin_bits_elemIdxInsideVd",
    )
    if _high(dut, "io_vecldin_valid") and not _high(dut, "io_vecldin_ready"):
        fields = _capture_fields(dut, field_names)
        if state["vector_hold_fields"] is None:
            state["vector_hold_fields"] = fields
            return False
        stable = state["vector_hold_fields"] == fields
        state["vector_hold_fields"] = fields
        return stable
    state["vector_hold_fields"] = None
    return False


def _check_vecldout_backpressure_proxy(dut):
    # The generated wrapper does not expose io_vecldout.ready, so use a visible
    # vec writeback hold proxy: vec result remains present without scalar feedback.
    return _high(dut, "io_vecldout_valid") and not _high(dut, "io_feedback_slow_valid")


def create_coverage_groups():
    """创建全部功能覆盖组。"""
    return [fc.CovGroup(name) for name in FG_NAMES]


def create_check_points_for_fg_api(g, dut):
    """实现本批次 FG-API 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-RESET-SEQUENCE": _check_reset_sequence,
            "CK-MULTI-CYCLE-STEP": _check_multi_cycle_step,
        },
        name="FC-RESET-AND-CLOCK",
    )

    g.add_watch_point(
        dut,
        {
            "CK-READY-HANDSHAKE": lambda x: _high(x, "io_ldin_valid") and _high(x, "io_ldin_ready"),
            "CK-BACKPRESSURE-HOLD": _check_scalar_backpressure_hold,
        },
        name="FC-SEND-SCALAR-LOAD",
    )

    g.add_watch_point(
        dut,
        {
            "CK-VECTOR-HANDSHAKE": lambda x: _high(x, "io_vecldin_valid") and _high(x, "io_vecldin_ready"),
            "CK-VECTOR-FIELD-FILL": lambda x: _high(x, "io_vecldin_valid") and (
                _sig(x, "io_vecldin_bits_mask") != 0
                or _sig(x, "io_vecldin_bits_reg_offset") != 0
                or _sig(x, "io_vecldin_bits_elemIdx") != 0
                or _sig(x, "io_vecldin_bits_elemIdxInsideVd") != 0
            ),
        },
        name="FC-SEND-VECTOR-LOAD",
    )

    g.add_watch_point(
        dut,
        {
            "CK-TLB-PMP-INJECT": lambda x: _high(x, "io_tlb_resp_valid")
            and (
                _high(x, "io_pmp_ld")
                or _high(x, "io_pmp_st")
                or _high(x, "io_pmp_mmio")
                or not _high(x, "io_tlb_resp_bits_miss")
            ),
            "CK-DCACHE-FORWARD-INJECT": lambda x: (
                _sig(x, "io_dcache_resp_bits_data") != 0
                or _high(x, "io_dcache_resp_bits_miss")
                or _high(x, "io_dcache_s2_mq_nack")
                or _high(x, "io_dcache_s2_bank_conflict")
                or _high(x, "io_lsq_forward_valid")
                or _high(x, "io_sbuffer_valid")
                or _high(x, "io_ubuffer_valid")
            ),
        },
        name="FC-INJECT-MEMORY-RESP",
    )

    g.add_watch_point(
        dut,
        {
            "CK-SCALAR-CAPTURE": lambda x: _high(x, "io_ldout_valid")
            and (
                _sig(x, "io_ldout_bits_data") != 0
                or _high(x, "io_ldout_bits_uop_robIdx_flag")
                or _high(x, "io_ldout_bits_uop_lqIdx_flag")
            ),
            "CK-VECTOR-AND-CONTROL-CAPTURE": lambda x: _high(x, "io_vecldout_valid")
            or _high(x, "io_wakeup_valid")
            or _high(x, "io_feedback_slow_valid")
            or _high(x, "io_rollback_valid"),
        },
        name="FC-COLLECT-WRITEBACK-FEEDBACK",
    )


def create_check_points_for_fg_arbitration(g, dut):
    """实现本批次 FG-ARBITRATION 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-OVER-VECTOR-SCALAR": lambda x: _high(x, "io_misalign_ldin_valid")
            and _high(x, "io_misalign_ldin_ready")
            and (_high(x, "io_vecldin_valid") or _high(x, "io_ldin_valid")),
            "CK-OVER-LOWER-PRIORITY-REPLAY": lambda x: _high(x, "io_misalign_ldin_valid")
            and _high(x, "io_misalign_ldin_ready")
            and _high(x, "io_replay_valid"),
        },
        name="FC-MISALIGN-PRIORITY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-OVER-ORDINARY-REPLAY": lambda x: _high(x, "io_replay_valid")
            and _high(x, "io_replay_bits_forward_tlDchannel")
            and _high(x, "io_replay_ready"),
            "CK-OVER-SCALAR": lambda x: _high(x, "io_replay_valid")
            and _high(x, "io_replay_bits_forward_tlDchannel")
            and _high(x, "io_ldin_valid")
            and _high(x, "io_replay_ready")
            and not _high(x, "io_ldin_ready"),
            "CK-REPLAY-INVALID-NO-STALL": _check_replay_invalid_no_stall,
        },
        name="FC-DCACHE-MISS-REPLAY-PRIORITY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-OVER-UNCACHE-LOWER": lambda x: _high(x, "io_fast_rep_in_valid")
            and _high(x, "io_lsq_uncache_valid")
            and _high(x, "io_dcache_req_valid")
            and not _high(x, "io_lsq_uncache_ready"),
            "CK-BELOW-DCACHE-MISS": lambda x: _high(x, "io_fast_rep_in_valid")
            and _high(x, "io_replay_valid")
            and _high(x, "io_replay_bits_forward_tlDchannel")
            and _high(x, "io_replay_ready"),
        },
        name="FC-FAST-REPLAY-PRIORITY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-UNCACHE-OVER-NC": lambda x: _high(x, "io_lsq_uncache_valid")
            and _high(x, "io_lsq_uncache_ready")
            and _high(x, "io_lsq_nc_ldin_valid")
            and not _high(x, "io_lsq_nc_ldin_ready"),
            "CK-NC-OVER-ORDINARY-REPLAY": lambda x: _high(x, "io_lsq_nc_ldin_valid")
            and _high(x, "io_lsq_nc_ldin_ready")
            and _high(x, "io_replay_valid")
            and not _high(x, "io_replay_bits_forward_tlDchannel")
            and not _high(x, "io_replay_ready"),
            "CK-UNCACHE-OVER-REPLAY-VECTOR-SCALAR": _check_uncache_over_lower_requests,
            "CK-NC-OVER-VECTOR-SCALAR": _check_nc_over_vector_scalar,
        },
        name="FC-UNCACHE-NC-PRIORITY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-HIGHCONF-OVER-VECTOR": lambda x: _is_high_conf_prefetch(x)
            and _high(x, "io_vecldin_valid")
            and _high(x, "io_canAcceptHighConfPrefetch"),
            "CK-VECTOR-OVER-SCALAR": lambda x: _high(x, "io_vecldin_valid")
            and _high(x, "io_ldin_valid")
            and _high(x, "io_vecldin_ready")
            and not _high(x, "io_ldin_ready"),
            "CK-LOWCONF-LOWEST": lambda x: _is_low_conf_prefetch(x)
            and (
                _high(x, "io_ldin_valid")
                or _high(x, "io_vecldin_valid")
                or _high(x, "io_replay_valid")
                or _high(x, "io_lsq_uncache_valid")
                or _high(x, "io_lsq_nc_ldin_valid")
            )
            and not _high(x, "io_canAcceptLowConfPrefetch"),
        },
        name="FC-PREFETCH-VECTOR-SCALAR-PRIORITY",
    )


def create_check_points_for_fg_forward_violation(g, dut):
    """实现本批次 FG-FORWARD-VIOLATION 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-SQ-FORWARD-DATA": _check_sq_forward_data_success,
            "CK-SBUFFER-FORWARD-DATA": _check_sbuffer_forward_data_success,
        },
        name="FC-STLD-FORWARD-SUCCESS",
    )

    g.add_watch_point(
        dut,
        {
            "CK-WAIT-FOR-DATA": lambda x: (
                _high(x, "io_lsq_forward_dataInvalid") or _high(x, "io_lsq_forward_dataInvalidSqIdx_flag")
            )
            and not _high(x, "io_ldout_valid"),
            "CK-REPLAY-WHEN-NOT-READY": _check_forward_not_ready_replay,
        },
        name="FC-STLD-FORWARD-DATA-NOT-READY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-MISMATCH-REDIRECT-OR-KILL": _check_forward_addr_mismatch_control,
            "CK-NO-WRONG-DATA": lambda x: (
                _high(x, "io_lsq_forward_addrInvalid") or _high(x, "io_lsq_forward_addrInvalidSqIdx_flag")
            )
            and not _high(x, "io_ldout_valid"),
        },
        name="FC-STLD-FORWARD-ADDR-MISMATCH",
    )

    g.add_watch_point(
        dut,
        {
            "CK-QUERY-ISSUE": lambda x: _high(x, "io_lsq_ldld_nuke_query_req_valid"),
            "CK-VIOLATION-CONTROL": lambda x: _high(x, "io_lsq_ldld_nuke_query_resp_valid")
            and (_high(x, "io_rollback_valid") or _high(x, "io_lsq_ldld_nuke_query_revoke")),
        },
        name="FC-LDLD-NUKE-QUERY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-STORE-QUERY-ISSUE": lambda x: _high(x, "io_lsq_stld_nuke_query_req_valid"),
            "CK-NUKE-RESULT-HANDLING": lambda x: (
                _high(x, "io_stld_nuke_query_0_valid") or _high(x, "io_stld_nuke_query_1_valid")
            )
            and _visible_cancel_or_rollback(x),
        },
        name="FC-STLD-NUKE-QUERY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-FAST-FWD-DATA": _check_l2l_fast_forward_proxy,
            "CK-FAST-FWD-FAIL-PATH": _check_l2l_fast_forward_fail_proxy,
        },
        name="FC-L2L-FAST-FORWARD",
    )


def create_check_points_for_fg_exception_control(g, dut):
    """实现本批次 FG-EXCEPTION-CONTROL 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-SINGLE-EXCEPTION": _check_single_exception,
            "CK-MULTI-EXCEPTION-PRIORITY": _check_multi_exception_priority,
        },
        name="FC-TLB-PMP-EXCEPTION-MERGE",
    )

    g.add_watch_point(
        dut,
        {
            "CK-DENIED-PROPAGATION": lambda x: _high(x, "io_dcache_resp_bits_tl_error_delayed_tl_denied")
            and _any_output_exception(x),
            "CK-CORRUPT-PROPAGATION": lambda x: _high(x, "io_dcache_resp_bits_tl_error_delayed_tl_corrupt")
            and not _high(x, "io_dcache_resp_bits_tl_error_delayed_tl_denied")
            and _any_output_exception(x),
        },
        name="FC-DCACHE-TL-ERROR-PROPAGATION",
    )

    g.add_watch_point(
        dut,
        {
            "CK-NORMAL-WAKEUP": lambda x: _high(x, "io_wakeup_valid") and not _high(x, "io_pmp_mmio"),
            "CK-MMIO-WAKEUP": lambda x: _high(x, "io_pmp_mmio") and _high(x, "io_wakeup_valid"),
        },
        name="FC-WAKEUP-GENERATION",
    )

    g.add_watch_point(
        dut,
        {
            "CK-STAGE2-FAST-FEEDBACK": _check_fast_feedback_proxy,
            "CK-STAGE3-SLOW-FEEDBACK": lambda x: _high(x, "io_feedback_slow_valid"),
        },
        name="FC-FEEDBACK-FAST-SLOW",
    )

    g.add_watch_point(
        dut,
        {
            "CK-LDLD-ROLLBACK": lambda x: _high(x, "io_lsq_ldld_nuke_query_resp_valid")
            and _high(x, "io_lsq_ldld_nuke_query_resp_bits_rep_frm_fetch")
            and _high(x, "io_rollback_valid"),
            "CK-STLD-REDIRECT": lambda x: (_high(x, "io_stld_nuke_query_0_valid") or _high(x, "io_stld_nuke_query_1_valid"))
            and _visible_cancel_or_rollback(x),
        },
        name="FC-ROLLBACK-REDIRECT",
    )


def create_check_points_for_fg_misalign_load(g, dut):
    """实现本批次 FG-MISALIGN-LOAD 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-DETECT-AND-ENQ": _check_misalign_detect_and_enqueue,
            "CK-NON-MISALIGN-NO-ENQ": lambda x: _high(x, "io_ldin_valid")
            and (_sig(x, "io_ldin_bits_src_0") & 0xF) == 0
            and not _high(x, "io_misalign_enq_req_valid"),
        },
        name="FC-MISALIGN-DETECT-ENQUEUE",
    )

    g.add_watch_point(
        dut,
        {
            "CK-FIRST-SPLIT-SUCCESS": lambda x: _check_misalign_split_success(x, final_split=False),
            "CK-FIRST-SPLIT-REPLAY": lambda x: _check_misalign_split_replay(x, final_split=False),
        },
        name="FC-MISALIGN-FIRST-SPLIT-RESP",
    )

    g.add_watch_point(
        dut,
        {
            "CK-SECOND-SPLIT-SUCCESS": lambda x: _check_misalign_split_success(x, final_split=True),
            "CK-SECOND-SPLIT-REPLAY": lambda x: _check_misalign_split_replay(x, final_split=True),
        },
        name="FC-MISALIGN-SECOND-SPLIT-RESP",
    )

    g.add_watch_point(
        dut,
        {
            "CK-WAKEUP-WHEN-NEEDED": _check_misalign_wakeup_when_needed,
            "CK-REPLAY-WHEN-NOT-WOKEN": _check_misalign_replay_when_not_woken,
        },
        name="FC-MISALIGN-WAKEUP-OR-REPLAY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-NO-CROSS-16B": lambda x: _high(x, "io_misalign_enq_req_valid")
            and _sig(x, "io_misalign_enq_req_bits_alignedType") == 0,
            "CK-CROSS-16B-PATH": lambda x: _high(x, "io_misalign_enq_req_valid")
            and (
                (_sig(x, "io_misalign_enq_req_bits_mask") & 0xFF00) != 0
                and (_sig(x, "io_misalign_enq_req_bits_paddr") & 0xF) != 0
            ),
        },
        name="FC-MISALIGN-BOUNDARY-HANDLING",
    )


def create_check_points_for_fg_mmio_load(g, dut):
    """实现本批次 FG-MMIO-LOAD 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-S0-WAKEUP": lambda x: _high(x, "io_lsq_uncache_valid")
            and _high(x, "io_lsq_uncache_ready")
            and _high(x, "io_wakeup_valid"),
            "CK-NO-DATA-BEFORE-S3": lambda x: _high(x, "io_lsq_uncache_valid")
            and _high(x, "io_wakeup_valid")
            and not _high(x, "io_ldout_valid"),
        },
        name="FC-MMIO-EARLY-WAKEUP",
    )

    g.add_watch_point(
        dut,
        {
            "CK-MMIO-WRITEBACK-TIMING": lambda x: _high(x, "io_ldout_valid") and _high(x, "io_ldout_bits_debug_isMMIO"),
            "CK-MMIO-DEBUG-FLAGS": lambda x: _high(x, "io_ldout_bits_debug_isMMIO")
            and not _high(x, "io_ldout_bits_debug_isNCIO"),
        },
        name="FC-MMIO-S3-WRITEBACK",
    )


def create_check_points_for_fg_noncacheable_load(g, dut):
    """实现本批次 FG-NONCACHEABLE-LOAD 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-FIRST-PASS-DETECT": lambda x: _high(x, "io_lsq_nc_ldin_valid")
            and _high(x, "io_lsq_nc_ldin_ready")
            and not _high(x, "io_dcache_req_valid"),
            "CK-NON-NC-NO-DOUBLE-PASS": lambda x: _high(x, "io_ldin_valid") and not _high(x, "io_lsq_nc_ldin_valid"),
        },
        name="FC-NC-ATTRIBUTE-DETECT",
    )

    g.add_watch_point(
        dut,
        {
            "CK-NO-TLB-REQ-SECOND-PASS": lambda x: _high(x, "io_lsq_nc_ldin_valid") and not _high(x, "io_tlb_req_valid"),
            "CK-NC-PATH-ENTER": _check_nc_path_enter,
            "CK-NC-NO-TLB-QUERY-WITH-CONTENTION": lambda x: _high(x, "io_lsq_nc_ldin_valid")
            and (
                _ordinary_replay_valid(x)
                or _high(x, "io_ldin_valid")
                or _high(x, "io_vecldin_valid")
            )
            and not _high(x, "io_tlb_req_valid"),
        },
        name="FC-NC-BYPASS-TLB",
    )

    g.add_watch_point(
        dut,
        {
            "CK-NC-FORWARD-SUCCESS": _check_nc_forward_success,
            "CK-NC-ADDR-MISMATCH": lambda x: (
                _high(x, "io_lsq_ldld_nuke_query_req_bits_is_nc") or _high(x, "io_lsq_ldin_bits_nc_with_data")
            )
            and _check_forward_addr_mismatch_control(x),
        },
        name="FC-NC-FORWARD-VIOLATION",
    )

    g.add_watch_point(
        dut,
        {
            "CK-RAR-RAW-FULL-REPLAY": lambda x: _high(x, "io_lsq_ldld_nuke_query_req_valid")
            and _high(x, "io_lsq_ldld_nuke_query_req_bits_is_nc")
            and not _high(x, "io_lsq_ldld_nuke_query_req_ready")
            and not _high(x, "io_ldout_valid"),
            "CK-RAR-RAW-NOTREADY-REPLAY": _check_nc_raw_notready_replay,
        },
        name="FC-NC-REPLAY-ON-RAR-RAW-PRESSURE",
    )

    g.add_watch_point(
        dut,
        {
            "CK-NC-WRITEBACK-DATA": _check_nc_writeback_data,
            "CK-NC-NO-SPURIOUS-REDIRECT": _check_nc_no_spurious_redirect,
        },
        name="FC-NC-LDOUT-WRITEBACK",
    )

    g.add_watch_point(
        dut,
        {
            "CK-NC-MISALIGN-BLOCK": lambda x: _is_nc_misaligned(x) and not _high(x, "io_ldout_valid"),
            "CK-NO-ORDINARY-MISALIGN-PATH": lambda x: _is_nc_misaligned(x)
            and not _high(x, "io_misalign_enq_req_valid"),
        },
        name="FC-NC-MISALIGN-UNSUPPORTED",
    )


def create_check_points_for_fg_prefetch(g, dut):
    """实现本批次 FG-PREFETCH 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-HIGHCONF-ACCEPT-WHEN-AVAILABLE": lambda x: _is_high_conf_prefetch(x)
            and _high(x, "io_canAcceptHighConfPrefetch"),
            "CK-HIGHCONF-BLOCK-WHEN-BUSY": lambda x: _is_high_conf_prefetch(x)
            and not _high(x, "io_canAcceptHighConfPrefetch")
            and (
                _high(x, "io_misalign_ldin_valid")
                or _high(x, "io_replay_valid")
                or _high(x, "io_fast_rep_in_valid")
                or _high(x, "io_lsq_uncache_valid")
                or _high(x, "io_lsq_nc_ldin_valid")
            ),
        },
        name="FC-HIGHCONF-PREFETCH-ACCEPT",
    )

    g.add_watch_point(
        dut,
        {
            "CK-LOWCONF-ONLY-WHEN-IDLE": lambda x: _is_low_conf_prefetch(x)
            and _high(x, "io_canAcceptLowConfPrefetch")
            and not (
                _high(x, "io_ldin_valid")
                or _high(x, "io_vecldin_valid")
                or _high(x, "io_replay_valid")
                or _high(x, "io_lsq_uncache_valid")
                or _high(x, "io_lsq_nc_ldin_valid")
            ),
            "CK-LOWCONF-LOWEST-PRIORITY": lambda x: _is_low_conf_prefetch(x)
            and not _high(x, "io_canAcceptLowConfPrefetch")
            and (
                _high(x, "io_ldin_valid")
                or _high(x, "io_vecldin_valid")
                or _high(x, "io_replay_valid")
                or _high(x, "io_lsq_uncache_valid")
                or _high(x, "io_lsq_nc_ldin_valid")
            ),
        },
        name="FC-LOWCONF-PREFETCH-ACCEPT",
    )

    g.add_watch_point(
        dut,
        {
            "CK-L1-TRAIN-ON-LOAD": lambda x: _high(x, "io_prefetch_train_l1_valid"),
            "CK-L1-TRAIN-FIELDS": lambda x: _high(x, "io_prefetch_train_l1_valid")
            and (
                _high(x, "io_prefetch_train_l1_bits_uop_robIdx_flag")
                or _sig(x, "io_prefetch_train_l1_bits_vaddr") != 0
                or _sig(x, "io_prefetch_train_l1_bits_meta_prefetch") != 0
            ),
        },
        name="FC-PREFETCH-TRAIN-L1",
    )

    g.add_watch_point(
        dut,
        {
            "CK-SMS-TRAIN-ON-LOAD": lambda x: _high(x, "io_prefetch_train_valid"),
            "CK-SMS-TRAIN-FIELDS": lambda x: _high(x, "io_prefetch_train_valid")
            and (
                _high(x, "io_prefetch_train_bits_uop_robIdx_flag")
                or _sig(x, "io_prefetch_train_bits_vaddr") != 0
                or _sig(x, "io_prefetch_train_bits_paddr") != 0
            ),
        },
        name="FC-PREFETCH-TRAIN-SMS",
    )


def create_check_points_for_fg_replay_kill(g, dut):
    """实现本批次 FG-REPLAY-KILL 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-MISS-TO-REPLAY": _check_miss_to_replay,
            "CK-REPLAY-REISSUE": lambda x: _high(x, "io_replay_valid")
            and _high(x, "io_replay_ready")
            and (_high(x, "io_tlb_req_valid") or _high(x, "io_dcache_req_valid")),
        },
        name="FC-DCACHE-MISS-REPLAY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-BANK-CONFLICT-DETECT": lambda x: _high(x, "io_dcache_s2_bank_conflict")
            and _high(x, "io_fast_rep_out_valid"),
            "CK-REPLAY-CAUSE-PRESERVE": _check_bank_conflict_replay_cause_preserved,
        },
        name="FC-BANK-CONFLICT-REPLAY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-MQ-NACK-DETECT": lambda x: _high(x, "io_dcache_s2_mq_nack") and _high(x, "io_fast_rep_out_valid"),
            "CK-RETRY-LATER": lambda x: _high(x, "io_fast_rep_in_valid")
            and not _high(x, "io_dcache_s2_mq_nack")
            and (_high(x, "io_tlb_req_valid") or _high(x, "io_dcache_req_valid")),
        },
        name="FC-MQ-NACK-REPLAY",
    )

    g.add_watch_point(
        dut,
        {
            "CK-REDIRECT-KILL": lambda x: _high(x, "io_redirect_valid") and _high(x, "io_dcache_s1_kill"),
            "CK-KILL-PROPAGATE": lambda x: _high(x, "io_redirect_valid")
            and _high(x, "io_dcache_s1_kill")
            and not _high(x, "io_ldout_valid")
            and not _high(x, "io_vecldout_valid"),
        },
        name="FC-S1-KILL-ON-REDIRECT",
    )

    g.add_watch_point(
        dut,
        {
            "CK-MISMATCH-KILL": lambda x: _high(x, "io_fast_rep_in_valid") and _high(x, "io_dcache_s1_kill"),
            "CK-NO-FALSE-KILL": lambda x: _high(x, "io_fast_rep_in_valid")
            and not _high(x, "io_dcache_s1_kill")
            and (_high(x, "io_dcache_req_valid") or _high(x, "io_fast_rep_out_valid")),
        },
        name="FC-S1-KILL-ON-FAST-REPLAY-MISMATCH",
    )

    g.add_watch_point(
        dut,
        {
            "CK-L2L-FAIL-KILL": _check_l2l_fail_kill_proxy,
            "CK-L2L-SUCCESS-NO-KILL": _check_l2l_success_no_kill_proxy,
        },
        name="FC-S1-KILL-ON-L2L-FAIL",
    )


def create_check_points_for_fg_scalar_pipeline(g, dut):
    """实现本批次 FG-SCALAR-PIPELINE 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-SINGLE-ACCEPT": lambda x: _high(x, "io_ldin_valid") and _high(x, "io_ldin_ready"),
            "CK-STALL-AND-RESUME": _check_scalar_stall_resume,
        },
        name="FC-SCALAR-HANDSHAKE",
    )

    g.add_watch_point(
        dut,
        {
            "CK-REQ-ISSUE-TIMING": lambda x: _high(x, "io_ldin_valid")
            and _high(x, "io_ldin_ready")
            and _high(x, "io_tlb_req_valid")
            and _high(x, "io_dcache_req_valid"),
            "CK-REQ-FIELD-MATCH": lambda x: _high(x, "io_tlb_req_valid")
            and _high(x, "io_dcache_req_valid")
            and _sig(x, "io_tlb_req_bits_vaddr") == _sig(x, "io_ldin_bits_src_0")
            and _sig(x, "io_dcache_req_bits_vaddr") == _sig(x, "io_ldin_bits_src_0"),
            "CK-NO-ISSUE-WHEN-S1-BLOCKED": lambda x: _high(x, "io_ldin_valid")
            and not _high(x, "io_ldin_ready")
            and not _high(x, "io_tlb_req_valid")
            and not _high(x, "io_dcache_req_valid"),
        },
        name="FC-SCALAR-TLB-DCACHE-REQ",
    )

    g.add_watch_point(
        dut,
        {
            "CK-HIT-DATA-WRITEBACK": lambda x: _high(x, "io_ldout_valid")
            and not _any_scalar_exception(x)
            and _sig(x, "io_ldout_bits_data") != 0,
            "CK-UOP-META-WRITEBACK": lambda x: _high(x, "io_ldout_valid")
            and _sig(x, "io_ldout_bits_uop_robIdx_value") == _sig(x, "io_ldin_bits_uop_robIdx_value")
            and _sig(x, "io_ldout_bits_uop_lqIdx_value") == _sig(x, "io_ldin_bits_uop_lqIdx_value"),
        },
        name="FC-SCALAR-HIT-WRITEBACK",
    )

    g.add_watch_point(
        dut,
        {
            "CK-HOLD-UNDER-BACKPRESSURE": _check_ldout_backpressure_hold,
            "CK-RELEASE-ON-READY": _check_ldout_release_on_ready,
        },
        name="FC-SCALAR-WRITEBACK-BACKPRESSURE",
    )


def create_check_points_for_fg_vector_load(g, dut):
    """实现本批次 FG-VECTOR-LOAD 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-VECTOR-ACCEPT": lambda x: _high(x, "io_vecldin_valid") and _high(x, "io_vecldin_ready"),
            "CK-VECTOR-BACKPRESSURE": _check_vector_backpressure_hold,
        },
        name="FC-VECTOR-HANDSHAKE",
    )

    g.add_watch_point(
        dut,
        {
            "CK-OFFSET-AND-MASK-PASS": lambda x: _high(x, "io_vecldout_valid")
            and _sig(x, "io_vecldout_bits_mask") == _sig(x, "io_vecldin_bits_mask")
            and _sig(x, "io_vecldout_bits_reg_offset") == _sig(x, "io_vecldin_bits_reg_offset"),
            "CK-ELEM-IDX-PASS": lambda x: _high(x, "io_vecldout_valid")
            and _sig(x, "io_vecldout_bits_elemIdx") == _sig(x, "io_vecldin_bits_elemIdx")
            and _sig(x, "io_vecldout_bits_elemIdxInsideVd") == _sig(x, "io_vecldin_bits_elemIdxInsideVd"),
        },
        name="FC-VECTOR-ADDR-MASK-INFO",
    )

    g.add_watch_point(
        dut,
        {
            "CK-VECDATA-WRITEBACK": lambda x: _high(x, "io_vecldout_valid")
            and _sig(x, "io_vecldout_bits_vecdata") != 0,
            "CK-EXCEPTION-FIELD-WRITEBACK": lambda x: _high(x, "io_vecldout_valid")
            and (
                _high(x, "io_vecldout_bits_hasException")
                or _any_high(
                    x,
                    "io_vecldout_bits_exceptionVec_3",
                    "io_vecldout_bits_exceptionVec_4",
                    "io_vecldout_bits_exceptionVec_5",
                    "io_vecldout_bits_exceptionVec_13",
                    "io_vecldout_bits_exceptionVec_19",
                    "io_vecldout_bits_exceptionVec_21",
                )
            ),
            "CK-VECLDOUT-BACKPRESSURE": _check_vecldout_backpressure_proxy,
        },
        name="FC-VECTOR-WRITEBACK",
    )

    g.add_watch_point(
        dut,
        {
            "CK-NO-SLOW-FEEDBACK": lambda x: _high(x, "io_vecldout_valid") and not _high(x, "io_feedback_slow_valid"),
            "CK-STILL-WRITES-BACK": lambda x: _high(x, "io_vecldout_valid"),
        },
        name="FC-VECTOR-NO-FEEDBACK-SLOW",
    )


def create_check_points_for_fg_writeback_data(g, dut):
    """实现本批次 FG-WRITEBACK-DATA 下的 FC/CK 覆盖定义。"""
    g.add_watch_point(
        dut,
        {
            "CK-DCACHE-SOURCE": _check_writeback_dcache_source,
            "CK-FORWARD-SOURCE": _check_writeback_forward_source,
            "CK-UNCACHE-SOURCE": lambda x: _high(x, "io_ldout_valid")
            and (_high(x, "io_ldout_bits_debug_isMMIO") or _high(x, "io_ldout_bits_debug_isNCIO")),
        },
        name="FC-DATA-SOURCE-SELECTION",
    )

    g.add_watch_point(
        dut,
        {
            "CK-LOW-HALF-EXTRACT": lambda x: _high(x, "io_ldout_valid")
            and (_sig(x, "io_ldout_bits_debug_paddr") & 0x8) == 0,
            "CK-HIGH-HALF-EXTRACT": lambda x: _high(x, "io_ldout_valid")
            and (_sig(x, "io_ldout_bits_debug_paddr") & 0x8) != 0,
            "CK-OFFSET-SELECT": lambda x: _high(x, "io_ldout_valid")
            and (_sig(x, "io_ldout_bits_debug_vaddr") & 0x7) == _sig(x, "io_lsq_ld_raw_data_addrOffset"),
        },
        name="FC-EXTRACT-128B-TO-64B",
    )

    g.add_watch_point(
        dut,
        {
            "CK-UNCACHE-DATA-PATH": _check_writeback_uncache_data_path,
            "CK-UNCACHE-META-PATH": lambda x: _high(x, "io_ldout_valid")
            and (_high(x, "io_ldout_bits_debug_isMMIO") or _high(x, "io_ldout_bits_debug_isNCIO"))
            and (
                _sig(x, "io_ldout_bits_uop_robIdx_value") != 0
                or _sig(x, "io_ldout_bits_uop_lqIdx_value") != 0
                or _sig(x, "io_ldout_bits_debug_paddr") != 0
            ),
        },
        name="FC-UNCACHE-DATA-WRITEBACK",
    )

    g.add_watch_point(
        dut,
        {
            "CK-LQ-INDEX-UPDATE": lambda x: _high(x, "io_ldout_valid")
            and _sig(x, "io_ldout_bits_uop_lqIdx_value") == _sig(x, "io_lsq_ldin_bits_uop_lqIdx_value"),
            "CK-DEBUG-ADDR-UPDATE": lambda x: _high(x, "io_ldout_valid")
            and (
                _sig(x, "io_ldout_bits_debug_vaddr") != 0
                or _sig(x, "io_ldout_bits_debug_paddr") != 0
                or _high(x, "io_ldout_bits_debug_isNCIO")
            )
            and _high(x, "io_lsq_ldin_bits_updateAddrValid"),
        },
        name="FC-WRITEBACK-META-UPDATE",
    )


def init_function_coverage(dut, cover_groups):
    """按覆盖组名称分派各组的 watch point 定义。"""
    coverage_init_map = {
        "FG-API": create_check_points_for_fg_api,
        "FG-ARBITRATION": create_check_points_for_fg_arbitration,
        "FG-SCALAR-PIPELINE": create_check_points_for_fg_scalar_pipeline,
        "FG-REPLAY-KILL": create_check_points_for_fg_replay_kill,
        "FG-FORWARD-VIOLATION": create_check_points_for_fg_forward_violation,
        "FG-EXCEPTION-CONTROL": create_check_points_for_fg_exception_control,
        "FG-VECTOR-LOAD": create_check_points_for_fg_vector_load,
        "FG-MISALIGN-LOAD": create_check_points_for_fg_misalign_load,
        "FG-MMIO-LOAD": create_check_points_for_fg_mmio_load,
        "FG-NONCACHEABLE-LOAD": create_check_points_for_fg_noncacheable_load,
        "FG-PREFETCH": create_check_points_for_fg_prefetch,
        "FG-WRITEBACK-DATA": create_check_points_for_fg_writeback_data,
    }

    for group in cover_groups:
        init_func = coverage_init_map.get(group.name)
        if init_func is not None:
            init_func(group, dut)


def get_coverage_groups(dut):
    """获取功能覆盖组列表。"""
    groups = create_coverage_groups()
    init_function_coverage(dut, groups)
    return groups
