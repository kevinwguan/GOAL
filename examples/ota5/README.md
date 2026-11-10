# Graph-ordered 5T OTA macro

From the repository root with GOAL and tools configured:

```sh
python examples/ota5/build.py --out build/ota5
```

The illustrative clean-room SPICE example is parsed into a diffusion graph,
ordered with bounded exact path cover, tiled into well groups, exported through
the LEF engine, and routed. n1 and tail stay internal; inp/inn/out/vdd/vss/bias
are the six external nets. The routed GDS is imported and re-abstracted into
`hardened/goal_ota5.{lef,gds,json}` and `goal_ota5_bb.v`. This is reusable
physical macro packaging, with block LVS and analog performance not tested.

The tested sky130A run measures 529um, 41 vias, zero detailed-route DRC and
zero Magic drc(full) errors on the hardened macro. The ordering is an exact
single-path cover. Fingers remain separate physical islands before routing;
no diffusion sharing is asserted. Physical passive PCells and mixed-bulk
well groups are unsupported. See [ENGINE.md](../../docs/ENGINE.md).
