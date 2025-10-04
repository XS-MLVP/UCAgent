/*
 * Module: Select table for radix-4 SRT division
 * Author: wangjunyue2001@gmail.com
 * Description: The data comes from `D. Harris, J. Stine, M. Ercegovac, A. Nannarelli, K. Parry, and C. Turek, “Unified Digit Selection for Radix-4 Recurrence Division and Square Root,” IEEE Transactions on Computers, vol. 73, no. 1, pp. 292–300, Jan. 2024, doi: 10.1109/TC.2023.3305760.`
 */

package divider

import spinal.core._

import scala.language.postfixOps

case class SelectTable() extends Module {
  val io = new Bundle {
    val sum   = in UInt (8 bits)
    val carry = in UInt (8 bits)
    val divD  = in UInt (3 bits)
    val qsm   = out UInt (4 bits)
    val p     = out UInt (7 bits)
  }
  private val sum = io.sum + io.carry
  private val p   = sum(7 downto 1).asSInt
  private def d   = io.divD
  io.p := p.asUInt
  /* Condition */
  private val m = Seq.fill(4)(UInt(8 bits))
  /* Thresholds */
  private val thresholds = Seq(
    Seq(-13, -14, -16, -17, -18, -20, -22, -23), // -1
    Seq(-4, -4, -6, -6, -6, -6, -8, -8),         // 0
    Seq(4, 4, 6, 6, 6, 6, 8, 8),                 // 1
    Seq(12, 14, 16, 17, 18, 20, 22, 23)          // 2
  )
  for (i <- thresholds.indices) {
    for (x <- thresholds(i).zipWithIndex) {
      m(i)(x._2) := p >= x._1
    }
  }
  private val mask = Vec.fill(4)(Bool())
  for (i <- mask.indices) {
    mask(i) := m(i)(d)
  }
  when(mask(3)) {
    io.qsm := U"4'b1000" // +2
  }.elsewhen(mask(2)) {
    io.qsm := U"4'b0100" // +1
  }.elsewhen(mask(1)) {
    io.qsm := U"4'b0000" // +0
  }.elsewhen(mask(0)) {
    io.qsm := U"4'b0010" // -1
  }.otherwise {
    io.qsm := U"4'b0001" // -2
  }
}
