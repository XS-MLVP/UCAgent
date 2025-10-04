/*
 * Module: 3-2 carry-save adder
 * Author: wangjunyue2001@gmail.com
 * Description: Reference from `https://github.com/openhwgroup/cvw/blob/2632a2e29641dbc63b303bf1ca77efec1d5b8e46/src/generic/csa.sv`
 */

package divider

import spinal.core._

import scala.language.postfixOps

case class CarrySaveAdder(Width: Int) extends Module {
  val io = new Bundle {
    val x, y, z   = in UInt (Width bits)
    val cin       = in Bool ()
    val cout, sum = out UInt (Width bits)
  }
  private val low = new Area {
    val x = io.x(Width - 2 downto 0)
    val y = io.y(Width - 2 downto 0)
    val z = io.z(Width - 2 downto 0)
  }
  io.sum := io.x ^ io.y ^ io.z
  io.cout := (low.x & (low.y | low.z) | (low.y & low.z)) @@ io.cin
}
