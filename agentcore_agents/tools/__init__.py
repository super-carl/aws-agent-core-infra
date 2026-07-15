"""SuperCarl agent tools.

The agent's tools are defined inline in ``app.py`` as thin wrappers that invoke
the Action Group executor Lambdas (``supercarl_people_search`` etc.). This
package is reserved for any local-only helper tools a deployer wants to add
without a Lambda round-trip.
"""
